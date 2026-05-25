# PageIndex 통합 — 아키텍처 Overview

## 배경

Valuator는 현재 SEC 10-K를 2000줄 청크로 잘라 Gemini에 병렬로 던져 `{relevant, extract}` 필터링만 한다 ([sec_tool.py:33,211](../../valuator/tools/sec_tool.py)). 문서 구조를 활용하지 않아 다음 한계가 있다.

- "Appendix A 참조" 같은 문서 내 교차참조 추적 불가
- 같은 사실이 여러 청크에 흩어지면 통합 못함
- 한국 공시(DART) PDF / 일반 PDF / TXT / MD 경로 자체가 없음
- 청크 단위 필터는 "어디에 있을 만한지" 추론을 못함

PageIndex(VectifyAI)는 문서를 계층 트리로 변환하고 LLM이 트리 위에서 추론으로 노드를 탐색하는 vectorless RAG. 이 접근을 Valuator의 SEC + DART + 일반 PDF/TXT/MD 시나리오에 통합한다.

핵심 사전 정보: Valuator는 이미 `ExplicitGeminiCache`([gemini_direct.py:54](../../valuator/models/gemini_direct.py#L54))로 큰 문서를 Gemini에 한 번 올리고 여러 질의에서 재사용하는 인프라를 가졌다. 검색 단계에서 그대로 활용한다.

---

## 데이터 흐름

### Offline / 사전 인덱싱

```
Document (PDF/TXT/MD)
   │
   ▼ [경계 1] Parser (포맷별) → list[Page] 정규화
list[Page]
   │
   ▼ [경계 2] TOC 감지 (TOCDetector)
DetectedTOC {toc_pages, raw_text} | None
   │
   ▼ [경계 3] TOC 변환 (transform_toc)
list[Outline] | None
   │
   ▼ [선택 경로] TOC anchor/section resolve
SectionNode {anchor, content_span, children}
   │
   ▼ [경계 4] 트리 빌드
       Outline destination_page가 Page.ordinal과 매핑됨 → process_toc_with_page_numbers
       Outline 매핑 실패 + DetectedTOC 있음 → toc_guided process_no_toc
       TOC 없음 → process_no_toc
       process_large_node_recursively
   ▼
IndexedDocument {doc_hash, tree: TreeNode}
   │
   ▼
Index Store (SQLite: doc_hash → tree_json)
```

### Online / 질의 시점

```
Sub-query + doc_hash
   │
   ▼
Index Store에서 tree 로드
   │
   ▼
LLM 추론: tree + sub_query → 관련 node_ids 선택
   │
   ▼
선택된 노드의 텍스트 lazy load (Page 저장소, ExplicitGeminiCache 재사용)
   │
   ▼
ToolResult {extracts, citations: [{node_id, page_range, source_locator}]}
   │
   ▼
Fact Extraction → Evidence Store ({tree_node_id, page_range, fact})
```

특징:
- 인덱싱과 검색이 시점적으로 분리. 인덱싱은 비싸지만 1회, 검색은 트리만 만지므로 저렴.
- 트리가 단일 도메인 객체로 존재 → SEC, DART, 일반 PDF/TXT/MD 모두 같은 추상으로 공유.
- citation이 트리 노드 + source_locator로 명확.

현재 runtime은 `TOCDetector`를 먼저 호출한다. TOC가 감지되면 `DetectedTOC.raw_text`를 별도 채널로 보존하고, 인덱싱 대상 page text에서는 감지된 TOC block만 제거한다. TOC와 본문이 같은 페이지에 공존할 수 있으므로 page ordinal 자체는 제거하거나 0으로 바꾸지 않는다.

그 다음 `transform_toc`가 raw TOC를 `Outline` 트리로 변환한다. PDF physical page 또는 marked-text `page_marker`처럼 TOC destination page가 `Page.ordinal`과 매핑 가능한 입력이면 `PageIndexer`가 LLM 트리 생성 없이 `process_toc_with_page_numbers`로 `TreeNode.page_range`를 직접 만든다. destination page가 매핑 불가능한 입력은 감지된 TOC를 guide로 넣는 `toc_guided process_no_toc`로 강등되고, TOC 자체가 없으면 plain `process_no_toc`로 간다.

추가로 anchor/section 레이어가 생겼다. 이 레이어는 `Outline` hierarchy를 유지하되 TOC destination page를 곧바로 `page_range`로 쓰지 않고, 해당 page 주변에서 실제 body heading anchor를 찾은 뒤 anchor-to-anchor `content_span`을 계산한다. 현재 구현은 `SectionNode` resolver까지이며, 기존 `TreeNode/page_range` 기반 indexer와 retriever를 완전히 교체한 상태는 아니다.

### 병렬 처리 경계

| 경계 | 정책 |
|------|------|
| TOC 감지 | first chunk LLM 1회 |
| TOC 변환 | raw TOC → `Outline` tree LLM 1회 |
| `process_toc_with_page_numbers` | 로컬 deterministic range build |
| 한 문서의 page group continue chain (no-TOC 경로) | 순차. 이전 누적 tree가 다음 delta prompt의 입력 |
| large-node recursive split | 같은 frontier의 disjoint page range만 bounded parallel |
| 여러 문서 인덱싱 | 문서별 bounded parallel |
| 같은 tree에 대한 여러 retrieve query | query별 bounded parallel |

초기 page group을 독립 subtree로 병렬 생성하고 merge하는 map-reduce 방식은 group 경계 섹션 품질과 merge 비용을 별도로 검증해야 하므로 현재 구현 범위에서 제외한다.

---

## PageIndex 핵심 메커니즘

벡터 RAG가 "임베딩 유사도로 청크를 찾는다"면, PageIndex는 **문서를 계층 트리로 만들고 LLM이 그 위를 추론으로 탐색**한다. 네 가지 메커니즘이 받친다.

### 1. 트리 구조 인덱싱 — TOC 우선, 추론 fallback

목표 설계에서는 문서의 TOC가 1차 ground truth다. 처음 N페이지를 token-bounded first chunk로 묶어 LLM 1회로 TOC span을 감지하고, 이후 TOC를 구조화한 뒤 본문 페이지에 매핑한다. TOC의 page number를 직접 쓰는 경로는 그 숫자가 PDF physical page 또는 marked-text `page_marker` ordinal로 매핑될 때만 탄다.

현재 PoC runtime은 TOC 우선 경로까지 연결되어 있다. `DetectedTOC.raw_text`는 `transform_toc`가 `Outline` 트리로 구조화하고, outline `destination_page`가 `Page.ordinal`로 매핑되면 해당 page number로 트리를 직접 만든다. 이 경로에서는 LLM이 TOC 숫자를 page_range로 추론하지 않으므로 AAPL처럼 TOC page number와 실제 filing page가 맞는 문서의 비용과 오류가 크게 줄어든다. TOC block은 page text에서 제거하지만, TOC와 본문이 같은 페이지에 공존할 수 있으므로 TOC page 전체를 빌드 대상에서 제외하지 않는다.

다만 page-level direct route는 TOC와 본문 heading이 같은 page에 섞이는 경우를 근본적으로 표현하지 못한다. 이를 보완하기 위해 `heading_anchor.py`와 `sections.py`가 추가됐다. 원칙은 다음과 같다.

- TOC는 section universe와 hierarchy의 source of truth다.
- physical/page marker는 위치 좌표계의 source of truth다.
- TOC page number는 body heading anchor를 찾는 search window로 쓴다.
- retrieval의 정확한 경계는 `page_range`가 아니라 `SectionSpan(start_position, end_position)`이다.
- `page_range`는 citation/display/fallback용 파생값이다.

한국어 heading은 일반 ASCII fuzzy matching으로 안정적으로 잡히지 않는다. `find_heading_anchor`는 기존 `jamo_fuzzy_key`를 사용해 한글 음절을 자모 키로 변환하고, page 전체가 아니라 1~3개 인접 line window를 비교한다. `DetectedTOC`가 있으면 TOC line 번호를 ignore set으로 넘겨 같은 페이지의 TOC 항목을 body anchor로 잘못 잡지 않게 한다.

### 2. 점진적 트리 빌드 (`generate_toc_init` + `generate_toc_continue`) — no-TOC 경로 한정

긴 문서는 LLM 컨텍스트에 한 번에 안 들어간다. 페이지를 토큰 그룹(`max_tokens=20000`)으로 나눠 순차 호출한다. 핵심 트릭은 **이전까지 누적된 트리를 JSON으로 직렬화해 다음 프롬프트에 포함**하는 것이다.

다만 PageIndex 원안에 가깝게 `generate_toc_continue`는 완성된 트리 전체를 다시 쓰지 않는다. 이전 트리는 context index로만 넣고, LLM 응답은 현재 그룹에서 새로 시작하거나 materially continue되는 top-level node delta만 반환한다. Valuator는 이 delta를 로컬에서 기존 트리에 병합한다. 이렇게 해야:

- 이전 노드가 LLM 재작성 과정에서 사라지는 위험이 줄어든다
- 출력 토큰이 전체 tree 크기에 비례해 커지는 문제를 줄인다
- group overlap으로 생긴 중복 node를 병합 로직에서 통제할 수 있다

즉 "tree를 계속 주입한다"는 말은 맞지만, **tree를 매번 새로 생성하라고 시키는 것과는 다르다.**

### 3. 재귀 분할 (`process_large_node_recursively`) — 트리의 깊이를 만드는 핵심

3갈래 어느 경로로 만든 1차 트리든 **거친 분할**이다. 보통 1~2 레벨이며, 한 노드가 수십 페이지·수만 토큰을 자손으로 가질 수 있다. 그 상태로는:

- 검색 단계에서 노드 단위 텍스트가 여전히 너무 커서 LLM이 받아야 할 토큰이 폭증한다
- 인용이 "10페이지 범위" 수준이라 트리 노드 ID 기반 citation의 가치가 떨어진다
- 교차참조("Appendix A 참조")를 따라가도 도착 노드가 너무 크면 추론이 다시 흐려진다

재귀 분할은 위반 노드(자손 페이지 > `max_page_num_each_node=10` 또는 자손 토큰 > `max_token_num_each_node=20000`)의 페이지 범위만 다시 `process_no_toc`에 입력해 자식 트리를 만들고 원래 노드의 `children`으로 병합한다. **같은 알고리즘을 재귀로 적용**하는 셈이라 트리 깊이를 알고리즘적으로 만들어내는 메커니즘이 이것 하나다.

PageIndex의 실용성은 1+2만으로는 부족하다. 1+2는 "거친 목차"를 만들 뿐이고, **3이 있어야 노드가 의미 단위로 충분히 작아져 트리 검색이 실질적 정밀도를 가진다.** 따라서 PoC의 1순위 측정 지표도 "재귀가 잘 동작하는가, 얼마나 깊어지는가, 무한 재귀에 걸리지 않는가"다.

종료 조건·보호 장치·산출 지표 상세는 [phase-1의 재귀 분할 절](phase-1-indexing-poc.md#재귀-분할-process_large_node_recursively) 참조.

### 4. 트리 기반 추론 검색

검색 시 트리(자식 ids + summary)를 LLM 프롬프트나 tool output으로 제공하고 어떤 노드들이 질의에 관련 있는지 선택하게 한다. 선택 후에만 해당 page/node text를 lazy load한다. 청크 단위 유사도 검색이 아니라 **문서 구조 안에서의 위치 추론**이다. 교차참조 추적, "어느 섹션을 봐야 하는지"의 도메인 직관이 여기서 나온다.

트리가 깊을수록(=3이 잘 동작했을수록) 검색 단계가 정밀해진다. 반대로 너무 깊으면 트리 자체가 프롬프트에 안 들어가서 검색이 lazy view(자식 이하 요약 압축)에 의존해야 한다 — 이 트레이드오프는 [phase-2](phase-2-retrieval-integration.md)에서 다룬다.

---

## 컴포넌트 책임 분할

| 컴포넌트 | 책임 | 위치 |
|---------|-----|----------|
| `DocumentLoader` / `DocumentIngest` (경계) | 입력 parser 정책 선택 + PDF/TXT/MD → `list[Page]` 정규화 | [`/valuator/documents/ingest.py`](../../valuator/documents/ingest.py) (신규) |
| `TOCDetector` (경계) | 처음 N페이지 first chunk 1회 판단으로 TOC page span과 raw TOC text 감지 | [`/valuator/documents/toc.py`](../../valuator/documents/toc.py) (신규) |
| `transform_toc` (경계) | raw TOC text → `list[Outline]` + metrics | [`/valuator/documents/toc.py`](../../valuator/documents/toc.py) |
| `find_heading_anchor` | TOC title → page 내부 body heading offset 매칭. 한국어는 자모 fuzzy + line window 기반 | [`/valuator/documents/heading_anchor.py`](../../valuator/documents/heading_anchor.py) |
| `resolve_toc_section_tree` | `Outline` hierarchy + `list[Page]` → `SectionNode(anchor, content_span)` tree | [`/valuator/documents/sections.py`](../../valuator/documents/sections.py) |
| `PageIndexer` | `list[Page]` + optional `DetectedTOC`/`list[Outline]` → `TreeNode`. TOC direct route, toc-guided fallback, no-TOC fallback + 재귀 분할 | [`/valuator/documents/indexer.py`](../../valuator/documents/indexer.py) (신규) |
| `IndexStore` | `doc_hash → tree_json` 영속화 | [`/valuator/documents/store.py`](../../valuator/documents/store.py) (신규) |
| `TreeRetriever` | 질의 + 트리 → 노드 선택. LLM 추론 | [`/valuator/documents/retriever.py`](../../valuator/documents/retriever.py) (신규) |
| `SECTool` / `DARTTool` / `PDFTool` | 위 컴포넌트들의 조합자. 외부 fetch만 직접. | 기존 도구 수정 |
| `fact_extraction` | 노드 텍스트 입력으로 사실 추출 | 기존 그대로 |
| `evidence/store.py` | `{tree_node_id, page_range}` 필드 추가 | 스키마 마이그레이션 |

---

## 경계와 도메인 타입 (CLAUDE.md 정합)

경계는 세 곳:

1. **`DocumentLoader` + `DocumentIngest`**: 외부 파일 → `list[Page]`. loader가 입력별 parser 정책을 선택하고 ingest에서 포맷별 파싱/디코딩이 끝난다.
2. **`TOCDetector`**: `list[Page]` → `DetectedTOC | None`.
3. **`transform_toc`**: `DetectedTOC` + `list[Page]` → `list[Outline] | None` + metrics.
4. **`PageIndexer.build_tree`**: `list[Page]` + optional `DetectedTOC`/`list[Outline]` → `TreeNode`. 트리가 만들어지면 그 이후로는 트리 내부에서 isinstance/validate/normalize 금지.

분기는 위 경계 안에서만 일어난다. 본체(`build_tree` 호출 이후, `TreeRetriever`, `fact_extraction`, `evidence_store`)는 도메인 타입을 받고 도메인 타입을 반환하는 business logic.

Pydantic 도메인 타입:

- `RawDocument`: `{source, raw_bytes_or_text, mime}` — 경계 입력
- `Page`: `{doc_id, ordinal, text, token_count, source_locator}` — 정규화
- `DetectedTOC`: `{toc_pages: list[int], raw_text: str}` — first-chunk TOC page span 감지 결과
- `Outline`: `{title, destination_page, children}` — TOC에서 얻은 recursive outline node. 전체 outline은 `list[Outline]`
- `HeadingAnchorMatch`: `{page_ordinal, local_start, local_end, matched_text, score, method, line_start, line_end, source_start, source_end}` — page 내부 heading 매칭 결과
- `SectionAnchor`: TOC title이 resolve된 실제 body heading 위치
- `SectionSpan`: `{start: DocumentPosition, end: DocumentPosition, page_range}` — anchor-to-anchor content 범위
- `SectionNode`: `{title, structure_path, destination_page, anchor, content_span, children}` — TOC hierarchy를 유지한 span-native section tree
- `TreeNode`: `{node_id, title, page_range, summary, children: list[TreeNode]}` — page_range는 ordinal 범위
- `IndexedDocument`: `{doc_id, doc_hash, page_count, tree}`
- `NodeSelection`: `{doc_id, selected_node_ids, reasoning}` — 검색 결과

---

## 포맷별 Parser 정책 (PDF / TXT / MD 통합)

PageIndex 로직(트리 빌드, 검색)은 입력 포맷과 무관하다. 포맷별 차이는 Parser 계층(`DocumentLoader` + `DocumentIngest`)에서만 흡수하고, 그 이후 도메인은 통일된 `list[Page]` 추상만 다룬다. 직접 CLI 입력은 확장자로 PDF physical-page loader 또는 TXT/MD `token_text` loader를 고르고, marked text marker 규칙과 source metadata는 manifest나 입력 어댑터가 제공한다.

| 포맷 | 분할 기준 | ordinal 의미 | source_locator |
|------|---------|------------|---------------|
| PDF | 물리 페이지 (PyMuPDF/PyPDF2) | 1-based page number | `{kind: "pdf_page", page: int}` |
| TXT | 고정 토큰 윈도우 (예: 2K 토큰) | 0-based segment index | `{kind: "char_range", start: int, end: int}` |
| MD | 고정 토큰 윈도우 (TXT와 동일) | 0-based segment index | `{kind: "char_range", start: int, end: int}` |
| Marked text | 입력 어댑터가 제공한 page marker (`boundary=start/end`) | marker의 page number | `{kind: "...", page: int, start: int, end: int}` |

MD를 헤딩 기반으로 안 나누는 이유: PageIndex 트리 빌드 단계의 LLM이 헤딩을 자체적으로 발견해 트리 구조에 반영한다. parser가 헤딩 기반 분할까지 하면 도메인이 갈라지고 알고리즘이 분기를 가져야 함. parser는 단순하게, 구조 발견은 LLM에게.

`marked_text` loader는 marker를 찾지 못하면 실패한다. 실제 page marker를 기대한 입력을 token window로 묵시적 downgrade하면 tree metadata와 page range가 성공처럼 보이면서 다른 의미가 되기 때문이다.

인용 시점: source_locator로 역참조 → 클라이언트가 포맷별 뷰로 점프 (PDF는 페이지, TXT/MD는 char offset 범위). 분기는 클라이언트 렌더링에서만, 도메인 로직에는 없음.

---

## 상태가 어디에 사는가

- **인덱싱 중간 상태(부분 트리)**: LLM 컨텍스트에 산다(PageIndex 원안). Phase 1에서는 실패 시 재실행한다.
- **완성된 트리**: `IndexStore` (SQLite).
- **노드 텍스트**: Page 저장소 (파일시스템 또는 SQLite blob). 트리에는 page_range만, 텍스트는 lazy load.
- **검색 추적**: 기존 trace 인프라(`session_viewer_api.py`) 재사용.

---

## Phase 로드맵

| Phase | 내용 | 소요 | 문서 |
|-------|-----|-----|-----|
| 1 | 인덱싱 PoC — TOC 감지·변환 + 3갈래 빌드 + 재귀 분할 (로컬 PDF/TXT/MD/marked text, Apple FY24 10-K와 한국 사업보고서가 메인) | 2-3일 | [phase-1-indexing-poc.md](phase-1-indexing-poc.md) |
| 2 | 검색 통합 (`TreeRetriever`, evidence_store) | 2-3일 | [phase-2-retrieval-integration.md](phase-2-retrieval-integration.md) |
| 5 | 비교 마일스톤 (청크 필터링, 벡터 RAG) | — | [phase-5-comparison.md](phase-5-comparison.md) |

---

## 결정 사항

| 항목 | 결정 |
|------|------|
| PoC 대상 문서 | 로컬 PDF/TXT/MD/marked text. Apple FY24 10-K와 한국 사업보고서가 메인 |
| 알고리즘 차용 범위 | 현재 runtime은 TOC 감지 + TOC 변환 + `process_toc_with_page_numbers` + toc-guided/no-TOC fallback + 재귀 분할 + 검색 |
| anchor/section 레이어 | `resolve_toc_section_tree` 구현 완료. 기존 `TreeNode/page_range` indexer 교체 전 단계 |
| 경로 분기 위치 | `run_page_index_poc.py`가 `TOCDetector`와 `transform_toc`를 호출하고 `PageIndexer.build_tree(..., detected_toc=..., outlines=...)`에 전달 |
| 인덱싱·검색 LLM | Gemini 3.1 Flash (전 단계 통일, `response_json_schema` 적용) |
| 트리 저장 위치 | `/valuator/documents/store.py` 신설 (`IndexStore` 컴포넌트) |

---

## 위험과 미해결 이슈

- **비용 미상**: 10-K 1편(~300페이지) 인덱싱 비용 → PoC로 측정. TOC direct route는 본 빌드 LLM 호출 수가 적어 저렴할 것으로 예상되나, 매핑 실패로 toc-guided/no-TOC fallback이 자주 발생하면 비용이 늘어난다
- **TOC 감지 정확도**: 한국 사업보고서/IR PDF는 TOC 페이지 식별이 미세할 수 있음 (form feed, footer noise). first-chunk detector가 놓치면 no_toc fallback으로 떨어져 비용이 커지므로 `toc_maybe_truncated`, multi-span, low-confidence 강등률을 PoC에서 측정
- **인덱싱 비결정성**: 같은 문서가 다른 트리 → 트리 캐시로 부분 완화
- **트리 비대 문제**: 1000+ 페이지에서 누적 트리 자체가 컨텍스트 초과 가능 → 가지치기 전략 미확정
- **재귀 분할 종료 보장**: 단일 페이지가 `max_token_num_each_node`를 넘으면 PageIndex 원안은 무한 재귀 → Phase 1에서 깊이 한도와 단일 페이지 보호 장치 도입 ([phase-1](phase-1-indexing-poc.md#재귀-분할-process_large_node_recursively))
