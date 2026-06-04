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

이 값은 문서 크기 기반 baseline budget이다. 같은 문서라도 query 난이도에 따라 필요한 탐색량은 달라진다. 예를 들어 "revenue recognition policy"처럼 특정 회계 note를 찾는 질의는 좁은 path 몇 개로 끝날 수 있지만, "AI capex가 향후 margin에 미치는 영향"처럼 여러 섹션의 capex, depreciation, segment commentary, risk factor를 종합해야 하는 질의는 더 많은 branch를 봐야 한다.

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

### Task difficulty multiplier

Full MCTS로 확장할 때는 document budget에 query 난이도 multiplier를 곱해 최종 search budget을 정해야 한다.

```text
base_budget = indexing_cost_usd / document_divisor
difficulty_multiplier = f(query, planner_context, early_tree_uncertainty)
retrieval_budget = clamp(
    base_budget * difficulty_multiplier,
    min_budget,
    max_budget,
)
```

난이도는 query 실행 전에 한 번만 정할 수도 있고, 탐색 중 관측되는 uncertainty로 갱신할 수도 있다.

사전 난이도 신호:

- 질의가 단일 fact lookup인지, 여러 섹션을 종합해야 하는지
- 질의에 비교, 추세, 원인, 영향, 리스크처럼 synthesis 단어가 있는지
- planner가 생성한 sub-query 수
- 필요한 evidence type 수 (financial statement, footnote, MD&A, risk factor 등)
- 사용자가 요구한 citation granularity

탐색 중 난이도 신호:

- 상위 node selection confidence가 낮거나 여러 sibling에 분산되는지
- 서로 다른 branch가 비슷한 value score를 받는지
- terminal evidence 후보가 없고 계속 큰 parent만 선택되는지
- 같은 질의에 필요한 evidence가 여러 top-level section에 걸치는지
- early answerability check가 "insufficient evidence"를 반환하는지

예시 정책:

```text
simple lookup      multiplier 0.5 ~ 1.0
normal retrieval   multiplier 1.0
multi-hop lookup   multiplier 1.5 ~ 2.0
synthesis query    multiplier 2.0 ~ 4.0
```

이 multiplier는 무제한 증액이 아니라 `max_budget`으로 상한을 둔다. 어려운 query일수록 더 많은 탐색 예산을 받을 수 있지만, budget을 넘으면 best-so-far evidence와 "충분하지 않음" 판단을 반환해야 한다.

## MCTS-style top-down search

레퍼런스 PageIndex 문서는 dashboard/API에서 LLM tree search와 value-function 기반 MCTS를 조합한다고 설명하지만, 공개 repo의 retrieval 코드는 `get_document_structure` / `get_page_content` tool만 제공한다. Valuator의 Phase 2 구현은 공개 구현과 호환되는 쪽으로, 우선 **budgeted top-down tree search**를 서버 내부에 넣는다.

MCTS가 한정된 예산 안에서 탐색한다는 말은 모든 노드를 균등하게 평가하지 않고, 지금까지의 평가 통계를 바탕으로 가장 유망한 가지에 다음 LLM 호출 예산을 배분한다는 뜻이다. 문서 retrieval에 맞추면 다음 구성이다.

**State**

현재 탐색 위치 또는 지금까지 선택한 경로다.
 
```text
root
└── Item 8
    └── Notes to Consolidated Financial Statements
        └── Revenue Recognition
```

하나의 state는 보통 현재 보고 있는 `TreeNode`이거나, root부터 현재 노드까지의 path다.

**Action**

현재 노드에서 다음에 inspect할 child를 고르는 것이다.

```text
현재 노드: Item 8
가능한 action:
- Consolidated Statements
- Notes
- Controls
- Revenue Recognition
```

retrieval에서는 action이 "이 child subtree를 더 본다"가 된다.

**Budget**

예산은 다음 형태로 제한할 수 있다.

- 최대 LLM 호출 수
- 최대 예상 비용 USD
- 최대 prompt/output token
- 최대 탐색 깊이
- 최대 wall time

Valuator의 현재 구현은 `retrieval_cost_budget_usd`를 주 예산으로 쓴다. 예를 들어 indexing 비용이 `$0.80`이고 `N=10`이면 retrieval tree search budget은 `$0.08`이다.

Full MCTS에서는 이 정적 budget에 task difficulty multiplier를 반영한다. 쉬운 lookup은 baseline보다 작은 budget으로 조기 종료하고, synthesis query는 더 큰 budget 안에서 여러 branch를 반복 탐색한다.

**Selection**

Full MCTS에서는 매 iteration마다 UCB/UCT 같은 점수로 다음 탐색 대상을 고른다.

```text
UCT = Q(node) / N(node)
      + c * sqrt(log(N(parent)) / N(node))
```

- `Q(node)`: 지금까지 이 노드가 유용하다고 평가된 점수 합
- `N(node)`: 이 노드를 방문한 횟수
- `c`: exploration 강도

이 식은 exploitation과 exploration을 같이 다룬다. 이미 좋아 보인 노드에는 더 많은 예산을 쓰되, 아직 덜 본 노드에도 일부 예산을 배정한다. 예를 들어 revenue recognition 질문에서 `Item 8 → Notes`가 유망해 보이면 더 깊게 내려가지만, 아직 평가하지 않은 `Risk Factors`도 질문과 관련 있어 보이면 예산 일부를 받을 수 있다.

**Expansion**

선택된 node가 아직 충분히 평가되지 않았다면 child 목록을 펼친다. 이때 전체 tree를 한 번에 보여주지 않고 현재 node와 immediate children만 보여준다.

```text
질문: Amazon의 revenue recognition 정책은 어디에 있는가?

현재 노드:
Item 8. Financial Statements

Children:
1. Consolidated Statements
2. Notes
3. Revenue Recognition
4. Segment Information

관련 child를 고르시오.
```

이 lazy child view가 prompt budget 절약의 핵심이다.

**Evaluation / Rollout**

전통적인 MCTS는 leaf까지 random rollout을 해보고 승률을 추정한다. 문서 retrieval에서는 random rollout 대신 LLM value 평가를 쓴다.

```text
이 node가 질문 답변에 필요한 evidence를 포함할 가능성은?
0.0 ~ 1.0 점수로 평가
```

또는 실제 구현에 더 가까운 형태로, LLM이 관련 child id와 confidence/reasoning을 반환하고 이 결과를 value처럼 쓴다.

```json
{
  "selected_node_ids": ["n.2.4"],
  "confidence": 0.82,
  "reasoning": "Revenue recognition is usually disclosed in accounting policy notes."
}
```

**Backpropagation**

선택한 child가 유용하다고 평가되면 그 경로의 부모 노드들에도 점수를 올린다.

```text
Revenue Recognition node score = 0.9

업데이트:
root 방문 +1, 가치 +0.9
Item 8 방문 +1, 가치 +0.9
Notes 방문 +1, 가치 +0.9
Revenue Recognition 방문 +1, 가치 +0.9
```

이 통계가 다음 iteration의 UCT 점수에 반영되어, 제한된 예산 안에서 유망한 path에 더 많은 탐색을 배분한다.

**Budget check**

각 selection/evaluation 호출 전에 예상 비용을 계산한다.

```text
남은 budget: $0.012
이번 child selection 예상 비용: $0.004
호출 가능
```

호출 가능하면 `spent += estimated_cost`로 누적한다. 다음 호출이 budget을 넘으면 탐색을 중단한다.

```text
남은 budget: $0.002
다음 호출 예상 비용: $0.004
중단
```

이때 지금까지 찾은 best terminal evidence nodes를 반환한다. 아직 terminal evidence가 부족하면 deterministic child fallback으로 종료 가능한 작은 후보를 만든다.

문서 retrieval에서 한정 예산 MCTS는 대략 다음처럼 움직인다.

```text
1. root children 평가
   spent $0.004
   Item 8 선택

2. Item 8 children 평가
   spent $0.008
   Notes 선택

3. Notes children 평가
   spent $0.012
   Revenue Recognition, Significant Accounting Policies 선택

4. Revenue Recognition이 3 pages / 8k tokens면 terminal evidence로 채택

5. Significant Accounting Policies가 12 pages / 30k tokens면 더 내려감

6. 예산이 남으면 추가 child 평가
   예산이 부족하면 deterministic fallback 또는 현재 best evidence 반환
```

핵심은 큰 parent를 골랐다고 그 `page_range` 전체를 answer prompt에 넣지 않는 것이다. 큰 parent는 routing node로만 쓰고, evidence는 가능한 작은 descendant node에서 가져온다.

### 현재 구현과 full MCTS의 간극

현재 구현은 완전한 rollout/backpropagation MCTS가 아니라 다음 성질을 가진 MCTS-style top-down search다.

- 한 번에 전체 tree를 보지 않고 현재 node의 children만 평가한다.
- budget 안에서 여러 branch를 선택해 병렬 evidence 후보처럼 유지한다.
- branch가 크면 계속 내려가고, 작으면 terminal evidence node로 채택한다.
- budget이 소진되면 value call을 멈추고 deterministic fallback으로 종료 가능한 evidence set을 만든다.
- budget은 `indexing_cost_usd / N` 기반의 문서 크기 baseline이며, query 난이도 multiplier는 아직 없다.
- 아직 node별 `visit_count`, `value_sum`, UCB selection, rollout/backpropagation이 없다.

Full MCTS로 확장하려면 다음 요소가 추가되어야 한다.

- node별 `visit_count`
- node별 `value_sum` / `mean_value`
- UCB/UCT 기반 다음 node 선택
- 여러 iteration loop
- LLM value function 호출
- path 단위 backpropagation
- task difficulty multiplier와 탐색 중 uncertainty 기반 budget 재배분
- budget 안에서의 best evidence set 선택

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
