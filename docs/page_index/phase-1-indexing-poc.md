# Phase 1 — 인덱싱 PoC

전체 아키텍처: [overview.md](overview.md)

## 목표

로컬 PDF/TXT/MD/marked text 문서로 PageIndex 알고리즘을 차용해 트리를 구축한다. 우선 구현은 **확실한 두 경로**(TOC + page numbers, no-TOC/toc-guided fallback)에 집중한다. SEC 10-K와 한국 사업보고서/IR 자료가 메인 타겟이며, 입력 fetch는 어댑터에 분리한다. `gemini_direct` + `response_json_schema`를 적용해 검증·재시도 부담을 줄이고, 인덱싱 결과·비용·시간을 측정한다.

## 알고리즘 차용 범위

**TOC 감지·변환**
- `toc_detector_chunk` — 처음 `toc_check_page_num=20` 페이지를 `toc_scan_max_tokens=20000` 안에서 하나의 chunk로 묶어 TOC page ordinal을 1회 LLM 호출로 추출
- `find_toc_pages` — chunk 응답의 ordinal을 검증하고 연속 span으로 병합
- `toc_transformer` — raw TOC 텍스트 → 구조화된 TOC entry tree
- `toc_index_extractor` — TOC entry를 PDF physical page 또는 marked-text `page_marker` ordinal에 매핑

**트리 빌드 — 3갈래**
- `process_toc_with_page_numbers`
- `process_no_toc` / `toc_guided process_no_toc` (fallback)

**검증·강등**
- TOC page number가 실제 `Page.ordinal`로 매핑되지 않으면 direct route를 만들지 않고 fallback한다.

**Anchor/section resolve**
- `find_heading_anchor` — TOC title을 candidate page 주변의 실제 body heading offset으로 매칭
- `detected_toc_line_numbers_by_page` — 같은 페이지의 TOC line을 anchor 후보에서 제외
- `resolve_toc_section_tree` — `Outline` hierarchy를 유지한 채 `SectionNode(anchor, content_span)` tree 생성

**no-TOC 경로 내부**
- `page_list_to_group_text(max_tokens=20000, overlap_page=1)`
- `generate_toc_init` — 첫 그룹의 초기 트리
- `generate_toc_continue` — 이전 누적 트리를 context로, 다음 그룹의 top-level **delta**만 반환 (원안 유지, 로컬에서 병합)

**3갈래 공통 후처리**
- `process_large_node_recursively` — 큰 노드를 다시 `process_no_toc`로 재분할

## 차이점 (원안 대비)

- LLM 호출은 `gemini_direct.generate_json(..., response_json_schema=...)` — litellm 제거, 출력 JSON 유효성을 schema로 강제해 형식 검증 부담을 줄임.
- 모델 ID는 exact string 우선. `gemini-3.1-flash`는 `gemini-3-flash-preview`로 정규화하지 않고 가격도 별도 계산.
- LLM 프롬프트의 page header는 `[ordinal N]`만 넣고 `source_locator`는 저장소에만 둠 (프롬프트 토큰 절약).
- `generate_toc_continue` 응답은 full tree가 아닌 delta — 누적 트리 사라짐 위험과 출력 토큰 폭증을 회피.
- 저장은 완성 트리 기준. 그룹/재귀/TOC detection 중간 체크포인트는 두지 않는다.
- TOC page number direct route가 실패하면 page_range를 보정하지 않고 `toc_guided/no_toc` 경로로 강등한다.
- PageIndex 원안처럼 모든 TOC entry를 LLM으로 검증하지 않는다. physical marker가 있는 입력에서는 deterministic anchor matcher를 먼저 쓰고, LLM fixer는 anomaly fallback으로 남긴다.
- 기존 `TreeNode.page_range` runtime은 유지하되, 별도 `SectionNode.content_span` resolver를 추가했다. 이 resolver가 안정화되면 retrieval의 실제 content load 단위를 page range에서 span으로 옮긴다.

## 경로 분기 정책 — 경계 책임으로

분기는 **indexer 입구에서 1회** 일어난다. 감지된 TOC raw text는 별도 채널로 보존하고, 인덱싱 대상 page text에서는 감지된 TOC block만 제거한다. TOC와 본문이 같은 페이지에 공존할 수 있으므로 TOC page 전체를 빌드 대상에서 제외하거나 ordinal 0으로 바꾸지 않는다.

```
list[Page]
   │
   ▼ [경계 1] TOCDetector.detect(pages) → DetectedTOC | None
DetectedTOC(toc_pages, raw_text) | None
   │
   ▼ [경계 2] transform_toc(...)
list[Outline] | None
   │
   ├── [선택] resolve_toc_section_tree(outlines, pages, detected_toc=...)
   │       → SectionNode(anchor, content_span)
   │
   ▼ [경계 3] PageIndexer.build_tree(pages, detected_toc=..., outlines=...)
   │   Outline destination_page가 Page.ordinal과 매핑됨 → process_toc_with_page_numbers
   │   Outline 매핑 실패 + detected_toc 있음           → toc_guided process_no_toc
   │   no detected_toc                              → process_no_toc
   ▼
TreeNode → 재귀 분할 → 완성
```

본체는 `Outline`과 `Page`만 본다. outline에 destination page가 있다는 사실만으로 direct route를 타지 않고, 그 숫자가 `Page.ordinal` 집합과 실제로 매핑될 때만 direct tree를 만든다. PDF physical page와 marked-text `page_marker` ordinal은 이 경로를 쓸 수 있고, token-window TXT/MD는 TOC 숫자가 있어도 fallback한다.

anchor/section resolver는 direct route의 한계를 보완한다. `Outline.destination_page`를 `TreeNode.page_range`의 시작점으로 즉시 채택하지 않고, 해당 page 주변에서 실제 heading text를 찾아 `SectionAnchor`를 만든다. 같은 page에 TOC와 본문 heading이 함께 있으면 `detected_toc_line_numbers_by_page`가 TOC line을 ignore set으로 제공해 body heading만 anchor로 잡는다.

이는 "rule-based branching 금지"를 위반하지 않는다 — 분기 자체가 **문서 입력의 본질적 분류**이며, 그 분류를 도메인 타입으로 표현해 본체에서는 타입의 형태만 다룬다.

fallback도 같은 경계 위에서 표현된다 — TOC direct route가 실패하면 `DetectedTOC` guide 또는 no-TOC route로 떨어진다.

## 변경 파일

| 파일 | 역할 |
|------|-----|
| [`/valuator/documents/types.py`](../../valuator/documents/types.py) (신규) | `RawDocument`, `Page`, `TreeNode`, `IndexedDocument`, `DetectedTOC`, `Outline` |
| [`/valuator/documents/ingest.py`](../../valuator/documents/ingest.py) (신규) | `RawDocument` → `list[Page]` 정규화. `DocumentLoader`가 PDF physical page, 토큰 윈도우 TXT/MD, regex 기반 marked text 파싱을 감춤 |
| [`/valuator/documents/toc.py`](../../valuator/documents/toc.py) (신규) | `TOCDetector` (첫 chunk 1회 LLM 판별 + 연속 페이지 묶기), `transform_toc` (raw TOC → `list[Outline]`) |
| [`/valuator/documents/heading_anchor.py`](../../valuator/documents/heading_anchor.py) (신규) | TOC title → body heading anchor 매칭. 한국어는 `jamo_fuzzy_key` + 인접 line window fuzzy |
| [`/valuator/documents/sections.py`](../../valuator/documents/sections.py) (신규) | `Outline` hierarchy를 `SectionNode(anchor, content_span)` tree로 resolve |
| [`/valuator/documents/indexer.py`](../../valuator/documents/indexer.py) (신규) | `PageIndexer.build_tree(pages, detected_toc=None, outlines=None)`. TOC direct route, toc-guided fallback, plain no-TOC fallback + 재귀 분할 |
| [`/valuator/documents/store.py`](../../valuator/documents/store.py) (신규) | `doc_hash → tree_json` SQLite 영속화 (`IndexStore`) |
| [`/scripts/run_page_index_poc.py`](../../scripts/run_page_index_poc.py) | 로컬 문서 입력 CLI. SEC fetch 없음. tree/usage/llm_calls JSONL 출력 |
| [`/scripts/export_sec_10k_text.py`](../../scripts/export_sec_10k_text.py) | 선택적 SEC 입력 어댑터. 10-K를 로컬 marked text로 저장 |
| [`/valuator/utils/llm_usage.py`](../../valuator/utils/llm_usage.py) | Gemini 3.1 Flash 가격을 Gemini 3과 별도 모델로 계산 |

## CLI 입력

직접 입력 실행은 확장자로 기본 loader를 고른다. PDF는 physical page를 보존하고, plain TXT/MD는 token window로 정규화한다. `doc_id`는 필요할 때만 한 문서에 대해 명시하고, 기본값은 파일 stem이다.

```bash
./venv/bin/python scripts/run_page_index_poc.py \
  --input-file data/4Q24_IR_Book_KOR.pdf \
  --model gemini-3.1-flash
```

문서 메타데이터와 parser 세부사항은 manifest로 넘긴다. marked text의 regex, marker boundary, source locator kind는 인덱싱 알고리즘 옵션이 아니므로 flat CLI 옵션으로 노출하지 않는다.

```json
{
  "documents": [
    {
      "input_file": "data/page_index/report.txt",
      "doc_id": "report",
      "loader": {
        "kind": "marked_text",
        "marker": {
          "regex": "Page (?P<page>\\d+)$",
          "locator_kind": "source_page",
          "page_group": "page",
          "boundary": "end"
        }
      }
    }
  ]
}
```

`marked_text` loader가 marker를 못 찾으면 token window로 조용히 fallback하지 않고 실패한다. 실제 페이지가 필요한 입력을 segment tree로 잘못 인덱싱하지 않기 위한 경계다.

SEC 10-K는 먼저 입력 파일로 export한다. SEC fetch와 reader footer marker 설정은 인덱서가 아니라 입력 어댑터 책임이며, export 스크립트가 `.page_index.json` sidecar manifest를 같이 만든다.

```bash
./venv/bin/python scripts/export_sec_10k_text.py --ticker AAPL --year 2024
./venv/bin/python scripts/run_page_index_poc.py \
  --manifest data/page_index/aapl-2024.page_index.json \
  --model gemini-3.1-flash
```

여러 문서는 입력 파일 단위로 병렬 인덱싱할 수 있다. 각 문서는 독립 writer/client를 쓰며, 같은 SQLite `IndexStore`에 최종 결과만 기록한다.

```bash
./venv/bin/python scripts/run_page_index_poc.py \
  --input-file data/4Q24_IR_Book_KOR.pdf \
  --input-file data/20260219_company_200600000.pdf \
  --document-concurrency 2 \
  --model gemini-3.1-flash
```

`data/page_index/*.txt`처럼 `[page N]` header가 들어간 PDF text export는 direct TXT 입력으로 넣지 않는다. token window ordinal과 source `[page N]`을 LLM이 혼동할 수 있다. 이런 파일은 `marked_text` manifest에서 `\\[page (?P<page>\\d+)\\]` header marker를 명시한다.

## TOC 감지 (`TOCDetector`)

`TOCDetector.detect(pages)`는 처음 `toc_check_page_num=20` 페이지를 `toc_scan_max_tokens=20000` 한도 안에서 하나의 first chunk로 묶고, LLM 1회로 TOC page ordinal을 추출한다. 현재 PoC CLI는 이 detector를 먼저 호출하고, 감지 결과가 있으면 indexer에 전달한다.

1. 첫 N페이지를 page ordinal marker와 함께 chunk text로 구성한다. token budget을 넘으면 page 경계에서 자르며, 첫 페이지가 budget보다 커도 최소 1페이지는 포함한다.
2. LLM은 `{has_toc, toc_page_ordinals, toc_text, confidence, reasoning}`을 반환한다.
3. `has_toc=false`, 빈 ordinal, confidence < `min_confidence=0.7`이면 `DetectedTOC = None`으로 강등한다.
4. 응답 ordinal이 scan chunk 밖이면 실패로 처리한다.
5. ordinal을 document order 기준 연속 span으로 묶고 가장 긴 span을 선택한다. 여러 span이면 metric으로 기록한다.
6. 선택 span이 scan chunk 마지막 페이지에 닿고 뒤에 페이지가 남아 있으면 `toc_maybe_truncated=true` metric을 남긴다.

detector는 first-chunk 판단과 명시적 강등만 수행한다. `toc_text`는 cover/header/body prose를 제외한 TOC listing만 담는다.

## TOC 변환과 빌드

`DetectedTOC`가 있으면 CLI는 먼저 `transform_toc`를 호출한다.

- `DetectedTOC.raw_text`를 `Outline(title, destination_page, children)` tree로 변환한다.
- PDF physical page 또는 marked-text `page_marker`처럼 page number가 `Page.ordinal`과 매핑 가능한 입력만 direct route를 탄다.
- token-window TXT/MD처럼 ordinal이 page number가 아니면 TOC 숫자가 있어도 fallback한다.
- `DetectedTOC.toc_pages`는 감지/metrics/후속 변환 입력으로 쓴다. 같은 페이지에 TOC와 본문이 함께 있을 수 있어 문서 페이지를 통째로 제거하지 않는다.
- 인덱싱 대상 page text에서는 `DetectedTOC.raw_text`와 매칭되는 TOC block만 제거한다. 이 처리로 TOC page number가 재귀 분할 프롬프트에 다시 섞이는 것을 막는다.
- TOC raw text의 `[ordinal N]` marker는 prompt에 넣기 전에 `[detected TOC page]`로 바꾼다. 모델이 TOC 페이지 ordinal을 body `page_range`로 복사하지 않게 하기 위해서다.

**`process_toc_with_page_numbers`**

Outline의 `destination_page`가 실제 `Page.ordinal` 집합에 있으면 그 숫자를 그대로 start ordinal로 쓴다. parent outline에 destination page가 없으면 자식들의 가장 이른 start를 parent start로 파생한다. sibling end는 다음 sibling의 start 직전으로 계산한다. 같은 page에서 여러 outline이 시작하면 같은 page range를 허용한다. 이 경로는 LLM tree generation을 호출하지 않는다.

## Anchor/section resolve

`process_toc_with_page_numbers`는 저렴하지만 page보다 작은 경계를 표현하지 못한다. `resolve_toc_section_tree`는 TOC-first 아이디어를 유지하면서 이 문제를 span 단위로 푼다.

```
Outline(title, destination_page, children)
   │
   ▼ find_heading_anchor_in_pages(title, candidate_page=destination_page, radius=1)
SectionAnchor(page_ordinal, local_start, local_end, score, method)
   │
   ▼ sibling anchor-to-anchor span 계산
SectionSpan(start_position, end_position, page_range)
   │
   ▼
SectionNode(title, structure_path, destination_page, anchor, content_span, children)
```

원칙:

- TOC hierarchy는 그대로 유지한다.
- TOC page number는 `page_range`가 아니라 anchor search window다.
- parent entry에 anchor가 없으면 자식 중 가장 이른 anchor를 effective start로 쓴다.
- section end는 다음 sibling의 effective start 직전이다. 다음 sibling이 page 중간에서 시작하면 이전 section span은 같은 page의 해당 offset 전까지 포함한다.
- document 마지막 section은 마지막 page 끝까지 이어진다.
- `SectionSpan.page_range`는 span에서 파생한 citation/display용 값이다.

한국어/혼합 문서 처리:

- `heading_anchor.py`는 page 전체 fuzzy가 아니라 line window fuzzy를 쓴다.
- window 크기는 기본 1~3 line이다. `연결\n재무상태표`처럼 PDF 추출이 제목을 여러 줄로 쪼개도 매칭된다.
- 비교 키는 `jamo_fuzzy_key`로 만든다. 한글 음절은 자모로 풀고 ASCII 알파벳/숫자는 uppercase로 유지한다.
- `DetectedTOC`가 주어지면 TOC raw text와 매칭되는 line 번호를 ignore set으로 넘겨, 같은 page의 TOC listing이 body anchor로 선택되는 것을 막는다.

현재 상태:

- resolver와 테스트는 구현 완료.
- 기존 `PageIndexer`/`TreeRetriever`가 아직 `SectionNode.content_span`을 저장·검색 단위로 쓰지는 않는다.
- 다음 단계는 `SectionNode`를 `IndexedDocument` metadata 또는 별도 section store에 기록하고, retrieval content load를 `page_range`에서 `content_span` slice로 옮기는 것이다.

**`toc_guided process_no_toc` fallback**

TOC entry가 비었거나 page number 매핑이 실패하면 감지된 TOC raw text를 guide prompt로 넣고 기존 `generate_toc_init/continue` 경로를 탄다. 모델이 문서 밖 `page_range`를 반환하면 TOC-guided 경로에 한해서 실제 문서 page와 겹치는 범위로 정규화한다. 문서 page와 전혀 겹치지 않는 child node는 버린다.

**`process_no_toc`**

`DetectedTOC`가 없거나 TOC transform이 실패하면 `page_list_to_group_text` → `generate_toc_init` → `generate_toc_continue` delta chain으로 간다.

## 재귀 분할 (`process_large_node_recursively`)

3갈래로 만들어진 1차 트리는 거친 분할이라 한 노드가 너무 많은 페이지/토큰을 포함하는 경우가 흔하다. 그 노드의 페이지 범위만 다시 `process_no_toc`에 입력해 자식을 생성하고 원래 노드의 위치에 병합한다. 3갈래 모두 공통 후처리로 적용된다.

### 트리거 조건

노드가 다음 중 하나라도 위반하면 분할 대상:
- 자손 페이지 수 > `max_page_num_each_node` (기본 10)
- 자손 텍스트 토큰 수 > `max_token_num_each_node` (기본 20000)

leaf부터 평가하지 않고 트리를 DFS 순회하면서 첫 위반 노드를 처리, 처리 후 갱신된 트리에서 다시 검색.

### 동작

1. 위반 노드의 `page_range`로 원본 `Page` 슬라이스 확보
2. 같은 batch frontier에서 ancestor/descendant 관계가 없고 page_range가 겹치지 않는 위반 노드를 묶음
3. 각 슬라이스에 `process_no_toc` 재호출 (`page_list_to_group_text` → `generate_toc_init` → delta `generate_toc_continue` chain)
4. batch 결과를 원래 노드의 `children`으로 deterministic 병합
5. 갱신된 트리 전체에서 위반 노드 재검색. 없으면 종료

### 종료 조건과 보호 장치

PageIndex 원안에는 명시적 보호 장치가 없어 단일 페이지가 `max_token_num_each_node`를 넘으면 무한 재귀 위험. Valuator 보강:

- **재귀 깊이 한도**: `max_recursion_depth=4`
- **단일 페이지 보호**: 한 페이지가 한도를 단독으로 넘기면 분할 시도 안 함 (leaf 유지)
- **진행 보장**: 재귀 결과가 원래 노드와 같은 단일 범위만 반환하면 해당 노드를 보호 목록에 넣고 재시도 안 함
- **병렬 한도**: disjoint recursive split batch만 `recursion_concurrency`로 제한 (기본 4)

## 병렬 처리 정책

| 경계 | 병렬화 | 이유 |
|------|--------|------|
| 문서 간 | `--document-concurrency` | 입력/트리/usage가 독립 |
| TOC 감지 | 순차 1회 | 첫 chunk를 한 번에 판단해 detector 복잡도를 낮춤 |
| 같은 tree의 large-node recursion | `--recursion-concurrency` (기본 4) | 현재 frontier의 disjoint page range만 독립 |
| 한 문서의 group continue chain | 순차 | 누적 tree dependency 보존 |

### 비용 영향

TOC direct route는 본 빌드 LLM 호출 수가 적어 가장 저렴하다. 강등이 발생하면 누적 호출 수가 늘어나므로 TOC page number 매핑 실패율이 비용 지표의 1차 변수가 된다. 재귀가 빈번한 문서(부록 비대, 한국 사업보고서)는 추가 호출 체인이 든다.

`continue` 응답은 누적 트리 전체가 아니라 delta다. 이전 트리는 입력 토큰으로 계속 들어가지만 출력 토큰은 다음 그룹에서 새로 시작하거나 이어지는 노드에 비례한다. 재귀 비용은 줄지 않으므로 `max_page_num_each_node`, `max_token_num_each_node`, `max_recursion_depth`를 비용 지표와 함께 조정한다.

## 검증 방법

1. **TOC 감지 정확도**: Apple FY24 10-K, 한국 사업보고서로 first-chunk detector가 올바른 페이지 구간을 찾는지 수동 대조. `toc_maybe_truncated`, multi-span, low-confidence 강등 케이스를 분리
2. **경로 분포**: 입력 문서별 어느 갈래가 발동했는지, 강등 발생률
3. **트리 구조 검증**: 빌드된 트리 JSON 덤프 → 실제 목차와 수동 대조
4. **TOC direct route 정합**: TOC page number와 실제 `Page.ordinal` 매핑의 일치
5. **재귀 분할 동작**: 재귀 발생 노드 수, 깊이별 분포, 보호 장치 발동
6. **비용 측정**: TOC 감지 / TOC 변환 / 본 빌드 / verify / 재귀 분할 카테고리별 토큰·USD
7. **재현성**: 동일 문서 2회 인덱싱 시 트리 차이

## 산출 지표

- 인덱싱 LLM 호출 수 (`toc.detect.chunk`, `toc.transform`, `toc.extract`, 3갈래별 `build`, `verify`, `recursion.init`, `recursion.continue`)
- 인덱싱 토큰 비용 (입력/출력)
- 인덱싱 wall-clock 시간
- 트리 노드 수, 평균/최대 깊이
- **TOC 감지 적중률 (수동 대조)**
- **TOC 감지 multi-span 비율, `toc_maybe_truncated` 비율, no-TOC downgrade 사유**
- **3갈래 경로별 발동 비율, 강등 빈도**
- **TOC page number 매핑 실패율**
- **재귀 분할 발생 노드 수, 최대 재귀 깊이, 보호 장치 발동 횟수**
- 핵심 섹션 누락 여부 (수동 대조 결과)
- 동일 문서 재인덱싱 시 트리 일치율
