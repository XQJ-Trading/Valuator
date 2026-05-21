# Phase 1 — 인덱싱 PoC

전체 아키텍처: [overview.md](overview.md)

## 목표

로컬 TXT/MD/marked text 문서로 PageIndex `process_no_toc` 알고리즘을 차용해 트리를 구축한다. Apple FY24 10-K는 샘플 입력 중 하나일 뿐이며, 구현은 SEC/DART/PDF 같은 입력 어댑터와 분리한다. `gemini_direct` + `response_json_schema`를 적용해 검증·재시도 부담을 줄이고, 인덱싱 결과·비용·시간을 측정한다.

## 변경 파일

| 파일 | 역할 |
|------|-----|
| [`/valuator/documents/types.py`](../../valuator/documents/types.py) (신규) | Pydantic 도메인 타입: `RawDocument`, `Page`, `TreeNode`, `IndexedDocument` |
| [`/valuator/documents/ingest.py`](../../valuator/documents/ingest.py) (신규) | `RawDocument` → `list[Page]` 정규화. 토큰 윈도우 TXT/MD와 regex 기반 marked text 지원 |
| [`/valuator/documents/indexer.py`](../../valuator/documents/indexer.py) (신규) | `list[Page]` → `TreeNode`. PageIndex 알고리즘 차용 |
| [`/valuator/documents/store.py`](../../valuator/documents/store.py) (신규) | `doc_hash → tree_json` SQLite 영속화 (`IndexStore`) |
| [`/scripts/run_page_index_poc.py`](../../scripts/run_page_index_poc.py) | 로컬 문서 입력 CLI. SEC fetch 없음. tree/usage/llm_calls JSONL 출력 |
| [`/scripts/export_sec_10k_text.py`](../../scripts/export_sec_10k_text.py) | 선택적 SEC 입력 어댑터. 10-K를 로컬 marked text로 저장 |
| [`/valuator/utils/llm_usage.py`](../../valuator/utils/llm_usage.py) | Gemini 3.1 Flash 가격을 Gemini 3과 별도 모델로 계산 |

## 알고리즘 차용 범위

PageIndex 라이브러리를 의존성으로 도입하지 않고 핵심 알고리즘만 옮긴다. litellm 의존을 끊고 `gemini_direct`로 교체하기 위함.

차용 항목:
- `page_list_to_group_text(max_tokens=20000, overlap_page=1)` — 페이지를 토큰 기반 그룹으로 묶음
- `generate_toc_init` — 첫 그룹에서 초기 트리 생성
- `generate_toc_continue` — 이전 누적 트리를 context index로 포함하되, 응답은 다음 그룹의 top-level delta만 받음
- `process_large_node_recursively` — 큰 노드 재분할 (아래 별도 절)

차이점:
- TOC 분기 없앰 — 항상 `process_no_toc` 경로 (CLAUDE.md "rule-based branching 금지" 정합)
- `verify_toc` + `fix_incorrect_toc_with_retries`는 `response_json_schema` 강제로 부담 감소
- LLM 호출은 `gemini_direct.generate_json(..., response_json_schema=...)`.
- 모델 ID는 exact string을 우선한다. `gemini-3.1-flash`는 `gemini-3-flash-preview`로 정규화하지 않고, 가격도 Gemini 3과 별도로 계산한다.
- LLM 프롬프트의 page header는 `[ordinal N]`만 넣고 `source_locator`는 저장소에만 둔다. 프롬프트 토큰을 줄이기 위함.
- Phase 1 저장은 완성 트리 기준이다. 그룹/재귀 단위 체크포인트는 Phase 4 자동화에서 별도 설계한다.

## CLI 입력

기본 실행:

```bash
./venv/bin/python scripts/run_page_index_poc.py \
  --input-file data/page_index/aapl-2024.txt \
  --doc-id aapl-2024 \
  --model gemini-3.1-flash
```

SEC 10-K는 먼저 입력 파일로 export한 뒤 같은 CLI에 넘긴다. SEC fetch는 인덱서가 아니라 입력 어댑터 책임이다.

```bash
./venv/bin/python scripts/export_sec_10k_text.py \
  --ticker AAPL \
  --year 2024
```

실제 페이지 마커가 있는 텍스트는 marker regex를 넘긴다. 이 경우 2000토큰 segment가 아니라 marker의 page number가 `Page.ordinal`이 된다.
마커가 page footer면 기본값인 `--page-marker-boundary end`를 쓰고, page header면 `start`를 명시한다.

```bash
./venv/bin/python scripts/run_page_index_poc.py \
  --input-file data/page_index/aapl-2024.txt \
  --doc-id aapl-2024 \
  --output-prefix aapl-2024 \
  --page-marker-regex '\|\s*\d{4}\s+Form\s+[A-Z0-9-]+\s+\|\s*(?P<page>\d+)\s*$' \
  --page-marker-kind sec_filing_page \
  --page-marker-boundary end \
  --model gemini-3.1-flash
```

SEC/DART fetch는 이 스크립트 책임이 아니다. 외부 어댑터가 텍스트 파일이나 marked text를 만든 뒤 이 CLI에 넘긴다.

## 재귀 분할 (`process_large_node_recursively`)

`generate_toc_continue`로 만들어진 1차 트리는 거친 분할이라, 한 노드가 너무 많은 페이지/토큰을 포함하는 경우가 흔하다. 그 노드의 페이지 범위만 다시 `process_no_toc` 알고리즘에 입력하여 자식 노드를 생성하고 원래 노드의 위치에 병합한다.

### 트리거 조건

노드가 다음 중 하나라도 위반하면 분할 대상:
- 자손 페이지 수 > `max_page_num_each_node` (기본 10)
- 자손 텍스트 토큰 수 > `max_token_num_each_node` (기본 20000)

leaf 노드부터 평가하지 않고 트리를 DFS 순회하면서 만나는 첫 위반 노드를 처리, 처리 후 갱신된 트리에서 다시 검색하는 방식이 단순.

### 동작

1. 위반 노드의 `page_range`로 원본 `Page` 슬라이스 확보
2. 그 슬라이스에 `process_no_toc` 재호출 (`page_list_to_group_text` → `generate_toc_init` → delta형 `generate_toc_continue` 체인)
3. 결과 자식 트리를 원래 노드의 `children`으로 교체
4. 갱신된 트리 전체에서 위반 노드 재검색. 없으면 종료

### 종료 조건과 보호 장치

PageIndex 원안에는 명시적 보호 장치가 없어 단일 페이지가 `max_token_num_each_node`를 넘으면 무한 재귀 위험. Valuator 보강:

- **재귀 깊이 한도**: `max_recursion_depth=4` (트리의 4번째 깊이까지만 자동 분할, 그 이상은 그대로 둠)
- **단일 페이지 보호**: 한 페이지가 한도를 단독으로 넘기면 분할 시도 안 함 (그대로 leaf 유지). 한국어 PDF에서 발생 가능.
- **진행 보장**: 재귀 결과가 원래 노드와 같은 단일 범위만 반환하면 해당 노드를 보호 목록에 넣고 재시도하지 않음.

### 비용 영향

재귀가 발생한 노드마다 추가 LLM 호출 체인 (`init + continue×N`)이 든다. Apple 10-K 같은 균질한 문서는 재귀 발생률이 낮을 수 있지만, 부록이 비대한 보고서나 한국 사업보고서는 재귀가 빈번할 수 있어 PoC에서 측정 필요.

`continue` 응답은 전체 누적 트리가 아니라 delta만 반환한다. 이전 트리는 입력 토큰으로 계속 들어가지만, 출력 토큰은 다음 그룹에서 새로 시작하거나 이어지는 노드에 비례한다. 재귀 비용은 줄지 않으므로 `max_page_num_each_node`, `max_token_num_each_node`, `max_recursion_depth`를 비용 지표와 같이 조정한다.

## 검증 방법

1. **트리 구조 검증**: Apple FY24 10-K로 트리 생성 후 JSON 덤프 → 실제 10-K 목차와 수동 대조
2. **누락 체크**: Item 1, 1A, 7, 7A, 8 등 핵심 섹션이 트리 노드로 추출되었는지 확인
3. **재귀 분할 동작**: 재귀가 발생한 노드 수, 깊이별 분포 로그 확인. 무한 재귀가 보호 장치(`max_recursion_depth`, 단일 페이지 보호)에 의해 차단되는지 확인
4. **비용 측정**: `LLMUsage`에서 인덱싱 카테고리별 토큰/시간/USD 합산
5. **재현성**: 동일 문서를 2회 인덱싱해 트리 차이 확인 (비결정성 정도 파악)

## 산출 지표

- 인덱싱 LLM 호출 수 (`init`, `continue`, `large_node_recursion.init`, `large_node_recursion.continue`별)
- 인덱싱 토큰 비용 (입력/출력)
- 인덱싱 wall-clock 시간
- 트리 노드 수, 평균 깊이, 최대 깊이
- **재귀 분할 발생 노드 수, 최대 재귀 깊이, 재귀가 차지하는 토큰 비용 비율**
- **보호 장치 발동 횟수** (`max_recursion_depth` 도달, 단일 페이지 한도 초과)
- 핵심 섹션 누락 여부 (수동 대조 결과)
- 동일 문서 재인덱싱 시 트리 일치율
