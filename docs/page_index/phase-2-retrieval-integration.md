# Phase 2 — 검색 통합

전체 아키텍처: [overview.md](overview.md). 선행: [Phase 1](phase-1-indexing-poc.md).

## 목표

Phase 1에서 생성된 트리를 실제 질의 흐름에 끼워 넣는다. PageIndex 원안처럼 먼저 구조만 보여주고, LLM이 필요한 노드/페이지를 고른 뒤 본문을 lazy load한다. 단, routing 단계에서 큰 부모 노드가 선택되더라도 그 부모의 전체 `page_range`를 바로 evidence로 사용하지 않는다. 큰 노드는 하위 노드를 고르는 길찾기 단위로만 쓰고, 답변 프롬프트에는 작고 충분한 evidence 노드의 본문만 넣는다.

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
4. `TreeRetriever.select(doc_id, tree, sub_query)` → routing 후보 `NodeSelection{selected_node_ids, reasoning}`
5. 선택된 routing 후보가 evidence 제한을 넘고 children을 가지면, 해당 subtree 안에서 다시 `select`를 호출해 더 작은 descendant 후보로 내려간다.
6. 최종 evidence 후보는 노드별 page/token 제한을 만족하거나 더 내려갈 children이 없는 노드다. 작은 sibling들이 모두 선택됐고 parent도 제한 안에 있으면 parent로 병합할 수 있다.
7. 최종 evidence 노드의 텍스트만 lazy load (`IndexStore.get_pages(doc_hash, start, end)`). 필요하면 노드 텍스트를 `ExplicitGeminiCache`에 올림
8. 기존 `fact_extraction` 파이프라인에 입력
9. `evidence_store`에 `{doc_id, tree_node_id, page_range, fact}` 저장

## CLI smoke test

Phase 1 인덱싱이 끝난 문서는 바로 retrieve smoke test를 할 수 있다.

```bash
./venv/bin/python scripts/run_page_index_retrieve_poc.py \
  --db data/page_index.db \
  --doc-id aapl-2024 \
  --query "Where is revenue recognition discussed?" \
  --model gemini-3.1-flash-lite
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
  --model gemini-3.1-flash-lite
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
    def __init__(
        self,
        client: LlmClient,
        *,
        max_evidence_pages_per_node: int = 5,
        max_evidence_tokens_per_node: int = 20_000,
        max_refinement_depth: int = 6,
        retrieval_cost_budget_usd: float = 0.10,
    ) -> None

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
- `select()`는 기존 호환용 global routing 선택이다. `retrieve()`는 기본적으로 전체 트리를 한 번에 넣지 않고 budgeted top-down tree search로 evidence 노드를 찾는다.

PageIndex의 `get_document_structure` / `get_page_content` tool 패턴은 Valuator에서는 다음 두 책임으로 나눈다.

- `get_document_structure`: `TreeNode`를 text-stripped JSON으로 직렬화. 본문은 절대 포함하지 않는다.
- `get_page_content`: 선택된 `node_id`의 `page_range`로 `IndexStore.get_pages()`를 호출해 원문 페이지 텍스트만 가져온다.

따라서 retrieval 단계에서 계속 주입되는 것은 "문서 전체 본문"이 아니라 "트리 구조 + 요약"이다. 본문은 refine이 끝난 작은 evidence 범위만 늦게 들어온다.

## Minimal evidence refinement 정책

Retrieval은 routing node와 evidence node를 분리한다.

- **Routing node**: tree search에서 방향을 잡는 노드. 큰 section, item, note parent가 선택될 수 있다.
- **Evidence node**: answer/fact extraction에 원문을 제공하는 노드. 기본적으로 `max_evidence_pages_per_node`와 `max_evidence_tokens_per_node` 안에 있어야 한다.

`retrieve()`는 다음 규칙을 적용한다.

1. 문서 root에서는 전체 descendant tree를 보여주지 않고, 현재 노드와 immediate children 요약만 보여준다.
2. LLM이 inspect할 child node들을 고르면, 각 child에 대해 같은 절차를 반복한다.
3. 선택된 노드가 evidence 제한 안에 있거나 leaf면 그대로 evidence로 채택한다.
4. 선택된 노드가 크고 children이 있으면 그 subtree의 immediate children만 다시 보여주고 더 작은 descendant 후보로 내려간다.
5. LLM이 같은 큰 부모를 다시 고르거나 빈 결과를 내면, 직접 children을 후보로 삼아 계속 내려간다. 이 fallback은 큰 부모 원문을 그대로 넣는 실패 모드를 막기 위한 안전장치다.
6. 중복 descendant와 ancestor가 함께 선택되면 더 구체적인 descendant를 우선한다.
7. 선택된 sibling들이 parent 전체를 사실상 덮고 parent도 evidence 제한 안에 있으면 parent로 병합한다.

## Retrieval search budget

PDF index/query 경로의 indexing, retrieval, answer 모델은 `gemini-3.1-flash-lite`를 기본으로 사용한다. 단, retrieval search budget은 indexing/answer 생성 비용과 분리한다.

`TreeRetriever`의 fallback search budget은 `retrieval_cost_budget_usd=0.10`이다. 실제 PDF/CLI query 경로에서는 문서별 indexing 비용을 알 수 있으면 `indexing_cost_usd / N`을 search budget으로 사용한다. 현재 기본 `N`은 `10`이다. 문서가 클수록 indexing 비용이 커지고, 그에 따라 retrieval tree search budget도 자연스럽게 커진다.

이 예산은 retrieval 단계의 tree navigation LLM 호출에만 적용한다. 이후 `AnswerGenerator`가 수행하는 답변 생성 비용은 별도 단계로 추적한다.

Budget enforcement는 호출 전 추정 방식이다.

- 모델 가격은 `valuator.utils.llm_usage.get_model_price(client.model)`에서 가져온다.
- indexing 직후에는 `llm_usage.jsonl`의 `TOTAL.cost_usd`를 `IndexedDocument.metadata["indexing_cost_usd"]`에 저장한다.
- query 경로는 metadata의 `indexing_cost_usd`만 budget source로 사용한다. 이 값이 없으면 stale usage 파일을 재해석하지 않고 fallback budget을 쓴다.
- prompt/system/schema 길이를 대략 4 chars/token으로 추정한다.
- selection 응답은 `max_output_tokens=512`로 제한하고, 해당 output token 비용을 예산에 반영한다.
- 다음 selection 호출의 추정 비용이 남은 budget을 넘으면 LLM 호출을 건너뛰고 deterministic child fallback으로 내려간다.
- 가격 정보를 모르는 모델은 budget 추정 비용을 0으로 보고 기존 동작을 유지한다.

이 방식은 실제 provider usage와 1:1로 일치하는 과금 회계가 아니라, retrieval search가 runaway 호출로 번지는 것을 막기 위한 사전 차단 장치다. 실제 비용 기록은 기존 `llm_usage.jsonl`이 담당한다.

## MCTS-style top-down search

레퍼런스 PageIndex 문서는 dashboard/API에서 LLM tree search와 value-function 기반 MCTS를 조합한다고 설명하지만, 공개 repo의 retrieval 코드는 `get_document_structure` / `get_page_content` tool만 제공한다. Valuator의 Phase 2 구현은 공개 구현과 호환되는 쪽으로, 우선 **budgeted top-down tree search**를 서버 내부에 넣는다.

현재 구현은 완전한 rollout/backpropagation MCTS가 아니라 다음 성질을 가진 MCTS-style 탐색이다.

- 한 번에 전체 tree를 보지 않고 현재 node의 children만 평가한다.
- budget 안에서 여러 branch를 선택해 병렬 evidence 후보처럼 유지한다.
- branch가 크면 계속 내려가고, 작으면 terminal evidence node로 채택한다.
- budget이 소진되면 value call을 멈추고 deterministic fallback으로 종료 가능한 evidence set을 만든다.

이 단계의 목적은 prompt token을 줄이고 “큰 parent 선택 = 큰 원문 로드” 연결을 끊는 것이다. 필요하면 Phase 5에서 value score, visit count, UCB selection, rollout/backpropagation을 추가해 full MCTS로 확장한다.

이 정책의 목표는 PageIndex의 "structure first, tight page fetch" 패턴을 서버 내부 API에서도 강제하는 것이다. 프롬프트가 부모 노드를 골라도 코드가 바로 전체 page range를 로드하지 않으므로, `Item 8`처럼 30쪽이 넘는 부모 섹션이 answer prompt를 지배하는 상황을 피한다.

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
