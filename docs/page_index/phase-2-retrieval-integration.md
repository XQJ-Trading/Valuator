# Phase 2 — 검색 통합

전체 아키텍처: [overview.md](overview.md). 선행: [Phase 1](phase-1-indexing-poc.md).

## 목표

Phase 1에서 생성된 트리를 실제 질의 흐름에 끼워 넣는다. PageIndex 원안처럼 먼저 구조만 보여주고, LLM이 필요한 노드/페이지를 고른 뒤 본문을 lazy load한다. 선택된 노드 텍스트는 기존 `fact_extraction` 파이프라인에 연결하고, evidence_store에는 트리 노드 기반 인용 정보를 추가한다.

## 변경 파일

| 파일 | 역할 |
|------|-----|
| [`/valuator/documents/retriever.py`](../../valuator/documents/retriever.py) | `TreeRetriever`. 질의 + 트리 → `NodeSelection` → selected page lazy load |
| [`/valuator/documents/store.py`](../../valuator/documents/store.py) | `doc_hash`와 `doc_id` 조회, page range lazy load |
| [`/valuator/tools/page_index_tool.py`](../../valuator/tools/page_index_tool.py) | `page_index_retrieve` tool. Agent flow에서 indexed document 검색 |
| [`/valuator/evidence/store.py`](../../valuator/evidence/store.py) | evidence 스키마에 `tree_node_id`, `page_range` 컬럼 추가 (마이그레이션) |
| [`/scripts/run_page_index_retrieve_poc.py`](../../scripts/run_page_index_retrieve_poc.py) | real LLM retrieve smoke test CLI |

## 흐름

1. 입력 어댑터(SEC/DART/PDF/TXT)가 문서 fetch/parse → `RawDocument` + `doc_hash` 계산
2. `IndexStore.get(doc_hash)` 조회. 캐시 미스면 인덱싱 트리거 (Phase 1 경로)
3. `TreeRetriever.get_document_structure(tree)` 등가 view 생성: 본문 없이 `{node_id,title,page_range,summary,children}`만 전달
4. `TreeRetriever.select(doc_id, tree, sub_query)` → `NodeSelection{selected_node_ids, reasoning}`
5. 선택된 노드의 텍스트 lazy load (`IndexStore.get_pages(doc_hash, start, end)`). 필요하면 노드 텍스트를 `ExplicitGeminiCache`에 올림
6. 기존 `fact_extraction` 파이프라인에 입력
7. `evidence_store`에 `{doc_id, tree_node_id, page_range, fact}` 저장

## CLI smoke test

Phase 1 인덱싱이 끝난 문서는 바로 retrieve smoke test를 할 수 있다.

```bash
./venv/bin/python scripts/run_page_index_retrieve_poc.py \
  --db data/page_index.db \
  --doc-id aapl-2024 \
  --query "Where is revenue recognition discussed?" \
  --model gemini-3.1-flash-lite-preview
```

같은 indexed document에 대한 query들은 서로 독립이므로 병렬 batch로 돌릴 수 있다.

```bash
./venv/bin/python scripts/run_page_index_retrieve_poc.py \
  --db data/page_index.db \
  --doc-id aapl-2024 \
  --query "Where is revenue recognition discussed?" \
  --query "Where are cash and marketable securities described?" \
  --query "Where are supply chain risks discussed?" \
  --query-concurrency 3 \
  --model gemini-3.1-flash-lite-preview
```

출력 파일:
- `{prefix}-result.json` — 전체 결과(selected_node_ids, reasoning, 선택 노드별 page range, page text snippet, source_locator, usage 경로). 페이지 텍스트는 `--max-page-chars`로 truncate.
- `{prefix}-text.txt` — 선택 노드의 페이지 본문만 concat. truncate 없음. fact_extraction에 그대로 투입 가능한 plain text.
- `{prefix}-llm_calls.jsonl` / `{prefix}-llm_usage.jsonl` — LLM 호출·사용량 추적.

query batch 출력은 query별로 `-q1`, `-q2` suffix를 붙여 result/text/trace 파일을 분리한다. `TreeRetriever.retrieve_many(..., concurrency=N)`도 같은 경계를 라이브러리 API로 제공한다.

`--evidence-db`, `--session-id`, `--task-id`를 넘기면 선택 노드별 evidence row도 기록한다.

## TreeRetriever 인터페이스

```
class TreeRetriever:
    async def select(
        self,
        *,
        doc_id: str,
        tree: TreeNode,
        sub_query: str,
    ) -> NodeSelection

    def get_document_structure(self, tree: TreeNode) -> dict[str, Any]

    def get_page_content(
        self,
        *,
        store: IndexStore,
        doc_hash: str,
        tree: TreeNode,
        node_id: str,
    ) -> list[Page]

    async def retrieve_many(
        self,
        *,
        store: IndexStore,
        document: IndexedDocument,
        sub_queries: list[str],
        concurrency: int = 4,
    ) -> list[RetrievalResult]
```

- 트리 전체(요약 + 자식 ids)를 프롬프트에 포함
- LLM은 관련 `node_id` 리스트와 선택 근거를 JSON으로 반환 (`response_json_schema`)

PageIndex의 `get_document_structure` / `get_page_content` tool 패턴은 Valuator에서는 다음 두 책임으로 나눈다.

- `get_document_structure`: `TreeNode`를 text-stripped JSON으로 직렬화. 본문은 절대 포함하지 않는다.
- `get_page_content`: 선택된 `node_id`의 `page_range`로 `IndexStore.get_pages()`를 호출해 원문 페이지 텍스트만 가져온다.

따라서 retrieval 단계에서 계속 주입되는 것은 "문서 전체 본문"이 아니라 "트리 구조 + 요약"이다. 본문은 선택된 범위만 늦게 들어온다.

여러 query는 각각 같은 text-stripped tree를 보고 node selection을 수행하므로 병렬 처리 가능하다. 한 query 안에서 selected page load는 SQLite range read라 Phase 2에서는 동시화하지 않는다.

## 트리 navigation 정책 (재귀 깊이와의 트레이드오프)

[재귀 분할](phase-1-indexing-poc.md#재귀-분할-process_large_node_recursively)이 트리를 깊게 만들수록 검색 노드 단위가 작아져 정밀해진다. 그러나 트리 자체가 검색 프롬프트에 안 들어갈 위험도 같이 커진다. 두 단계 정책으로 다룬다.

### 기본: 1-shot 평탄 직렬화
트리 모든 노드(title + summary + children ids)를 펼쳐 프롬프트에 넣고 LLM이 한 번에 관련 `node_id`를 고른다. 검색 호출 1회로 끝나 가장 저렴. Apple 10-K 정도 균질 문서는 이 경로로 충분.

### 트리 토큰 초과 시: lazy view + expand
트리 직렬화가 검색 단계 컨텍스트 한도(예: 100K)를 넘으면 깊이별로 잘라낸다.
- 루트 + 자식 1단계만 펼치고 손자 이하는 한 줄 summary로 압축
- LLM이 더 봐야 한다고 판단한 노드를 `expand` 요청 (JSON으로 node_id 반환)
- 그 가지만 한 단계 더 펼쳐 재호출, 관련 node_id를 최종 선택

phase-1의 `max_recursion_depth=4` 제한으로 트리 깊이는 보통 5-6 레벨 이하. Apple 10-K는 lazy view 발동 빈도가 낮을 것으로 예상되지만, 한국 사업보고서나 부록이 방대한 보고서는 발동률이 PoC 측정 대상.

## 검증 방법

1. **동작 확인**: 실제 질의 흐름(Planner → Agent Loop → `page_index_retrieve`)에 트리 검색이 끼어들어 응답이 만들어지는지
2. **evidence 무결성**: 저장된 `tree_node_id`가 트리에 실제 존재하는지, `page_range`가 노드의 범위와 일치하는지
3. **citation 동작**: 클라이언트에서 인용 클릭 시 source_locator로 올바른 PDF 페이지/char range로 점프하는지
4. **정확도 비교는 Phase 5로 미룸** — Phase 2는 통합 동작만 확인

## 산출 지표

- 노드 선택 LLM 호출 토큰/시간 (질의당 평균)
- 질의당 선택된 노드 수, 노드 텍스트 총 토큰
- **lazy view 발동률, expand 호출 수** (트리 깊이가 검색 단계에 미치는 영향)
- evidence 레코드 무결성 (수동 샘플 검증, 100% 목표)
- 캐시 적중률 (`ExplicitGeminiCache`)
