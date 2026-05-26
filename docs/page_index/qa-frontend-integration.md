# PDF QA — Frontend + Backend 통합 설계

## 배경

[overview.md](overview.md)와 [phase-1-indexing-poc.md](phase-1-indexing-poc.md)에서 PDF 인덱싱 파이프라인이, [phase-2-retrieval-integration.md](phase-2-retrieval-integration.md)에서 `TreeRetriever` 기반 노드 선택까지 구축됐다. 현재 PoC는 CLI 진입점([scripts/run_page_index_poc.py](../../scripts/run_page_index_poc.py), [scripts/run_page_index_retrieve_poc.py](../../scripts/run_page_index_retrieve_poc.py))으로만 동작한다.

이 문서는 다음 세 가지를 정의한다:

1. **웹 UI에서 PDF 업로드 → 인덱싱 → 질의 → 답변** 흐름을 끝까지 묶는 데 필요한 새 컴포넌트.
2. 기존 PageIndex 컴포넌트와 새 컴포넌트의 **경계 분담**.
3. **새로 추가되는 도메인 단계**: retrieve 결과를 받아 자연어 답변을 생성하는 `AnswerGenerator`.

---

## 사용자 흐름

```
[웹 UI: pdf 탭]
  └─ 드래그앤드랍으로 .pdf 파일 업로드
       └─ POST /api/pdf/upload          (서버: data/page_index/uploads/<doc_id>.pdf 저장)
  └─ 업로드된 파일 리스트에서 'Index' 클릭
       └─ POST /api/pdf/{doc_id}/index  (서버: 동기 인덱싱 → 완료 시 응답)
       └─ 클라이언트는 응답 전까지 버튼을 'indexing..'으로 비활성화
  └─ 인덱싱 완료된 파일 선택 후 질문 입력 → 'Ask'
       └─ POST /api/pdf/{doc_id}/query  (서버: TreeRetriever + AnswerGenerator → 답변 + 인용)
       └─ UI에 답변과 참조 노드/페이지 표시
```

핵심 제약:
- **쿼리 범위는 단일 문서**. UI에서 한 PDF를 선택해야 질문 입력칸이 활성화된다.
- **동시 인덱싱 차단은 UI 버튼 비활성화로만 수행**. 서버는 별도 잠금을 두지 않는다 (로컬 단일 사용자 도구이고, 동시 호출 시 두 인덱싱 작업이 각자 끝까지 돌 뿐 데이터 무결성 문제가 없다 — `IndexStore.record`가 `doc_hash` UPSERT라서).

---

## 컴포넌트 변경 요약

| 영역 | 파일 | 변경 |
|------|------|------|
| 도메인 | [`valuator/documents/generator.py`](../../valuator/documents/generator.py) (신규) | `AnswerGenerator`: retrieve 결과 + 질문 → 답변 + citations |
| 도메인 | [`valuator/documents/types.py`](../../valuator/documents/types.py) | `Answer` Pydantic 추가 |
| 도메인 | [`valuator/documents/__init__.py`](../../valuator/documents/__init__.py) | `Answer`, `AnswerGenerator` export |
| 서버 | [`server/pdf_api.py`](../../server/pdf_api.py) (신규) | `/api/pdf` 라우터: upload, list, index, query |
| 서버 | [`server/main.py`](../../server/main.py) | 라우터 등록 |
| 클라이언트 | [`client/src/api.ts`](../../client/src/api.ts) | `ActivityView`에 `"pdf"` 추가 + API 래퍼 |
| 클라이언트 | [`client/src/components/ActivitySidebar.tsx`](../../client/src/components/ActivitySidebar.tsx) | "pdf" 아이콘/항목 추가 |
| 클라이언트 | [`client/src/components/PdfView.tsx`](../../client/src/components/PdfView.tsx) (신규) | 드래그앤드랍 + 파일 리스트 + 인덱싱 버튼 + 질의 박스 |
| 클라이언트 | [`client/src/components/PdfView.module.css`](../../client/src/components/PdfView.module.css) (신규) | 스타일 |
| 클라이언트 | [`client/src/AppDesktop.tsx`](../../client/src/AppDesktop.tsx) | `activityView === "pdf"` 분기 |

---

## 새 도메인 컴포넌트: `AnswerGenerator`

### 책임

`TreeRetriever.retrieve()`가 반환하는 `RetrievalResult`(질의 + 선택된 노드 + 노드별 로드된 페이지 텍스트)를 받아, LLM 1회로 답변과 인용을 생성한다.

### 인터페이스 (경계: 외부 LLM 호출)

```python
class Answer(BaseModel):
    doc_id: str
    doc_hash: str
    query: str
    answer: str
    citations: list[AnswerCitation]
    used_node_ids: list[str]

class AnswerCitation(BaseModel):
    node_id: str
    page_range: list[int]  # [start, end]
    snippet: str

class AnswerGenerator:
    def __init__(self, client: LlmClient) -> None: ...

    async def generate(
        self,
        *,
        retrieval: RetrievalResult,
        trace_method: str = "page_index.answer",
    ) -> Answer:
        ...
```

### 프롬프트 구조

`response_json_schema`로 강제하여 답변과 인용을 JSON으로 받는다. CLAUDE.md의 "경계에서 변환 완결" 원칙에 따라, LLM 응답은 `Answer` Pydantic으로 즉시 검증된다. 답변 본문에서 인용한 `node_id`는 retrieval이 로드한 노드 집합 내에 있어야 한다 (경계 검증).

시스템 프롬프트:
> "Return JSON only. Answer the question using ONLY the provided document excerpts. Cite the node_id and page range for each claim. If the excerpts do not contain enough information, say so explicitly."

사용자 프롬프트는 각 retrieved 노드의 (title, page_range, text)를 직렬화해서 넣는다. 페이지 텍스트는 페이지 단위로 인용 가능하도록 노드 ID와 함께 라벨링한다.

### LLM 선택

[overview.md](overview.md)의 "결정 사항" 표에 따라 indexing/retrieval과 동일하게 **Gemini 3.1 Flash Lite**를 사용한다.

### 토큰 예산

retrieve가 반환한 페이지 텍스트가 컨텍스트를 초과하지 않도록, `RetrievalResult.selected_nodes`의 페이지를 그대로 사용한다. PageIndexer의 `max_token_num_each_node`(기본 20000) 보장이 있어 단일 노드는 한 LLM 호출에 들어간다. 다수 노드가 선택되어 합산 초과 가능성은 phase-2 기준 측정 결과 드물지만, 위험은 README에 명시한다.

---

## 서버 API 사양

라우터 prefix: `/api/pdf` (인증은 기존 `Depends(verify_auth)` 그대로 글로벌 적용).

### 저장 위치

- 업로드 PDF 원본: `data/page_index/uploads/<doc_id>.pdf`
- 인덱싱 산출물: `data/page_index/<doc_id>/tree.json` 등 (기존 PoC와 동일)
- SQLite: `data/page_index.db` (기존 그대로)

`doc_id`는 업로드된 파일 stem을 기반으로 생성. 중복 stem은 `-2`, `-3` 등으로 suffix. 이 정책은 `safe_output_prefix`와 동일한 정규화 + 충돌 해결 로직을 재사용한다.

### 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/pdf/upload` | multipart `file=@x.pdf` 업로드. `{doc_id, filename, size_bytes, indexed: bool}` 반환 |
| `GET`  | `/api/pdf` | 업로드된 PDF 리스트. 각 항목: `{doc_id, filename, size_bytes, indexed, doc_hash?, page_count?}` |
| `POST` | `/api/pdf/{doc_id}/index` | 동기 인덱싱. 완료까지 응답 보류. 끝나면 `{doc_id, doc_hash, page_count}` |
| `POST` | `/api/pdf/{doc_id}/query` | body: `{query: str}`. 응답: `Answer` 필드 + retrieved 노드 요약 |
| `DELETE` | `/api/pdf/{doc_id}` | (선택) 업로드 파일과 인덱스 제거. 1차 구현에서는 생략 가능 |

### 인덱싱 엔드포인트 동작

`POST /api/pdf/{doc_id}/index`는 [scripts/run_page_index_poc.py](../../scripts/run_page_index_poc.py)의 `index_input_document` 함수와 동일한 로직을 서버 컨텍스트에서 직접 수행한다 (subprocess 호출 X). 즉:

1. 업로드된 PDF를 읽어 `RawDocument` 생성
2. `DocumentLoader.pdf()`로 `list[Page]` 변환
3. `TOCDetector` → `transform_toc` → `PageIndexer.build_tree`
4. `IndexStore.record()`로 영속화

LLM 사용량/콜 로깅은 `PageIndexTraceWriter`를 그대로 사용. trace 파일은 `data/page_index/<doc_id>/` 아래.

**동기**로 응답한다. 인덱싱이 수십 초 ~ 수 분 걸릴 수 있으므로 클라이언트는 fetch timeout을 길게 잡아야 한다 (300초). 비동기 큐/SSE 도입은 차후.

### 질의 엔드포인트 동작

1. `IndexStore.get_by_doc_id(doc_id)`로 `IndexedDocument` 로드. 없으면 404
2. `TreeRetriever(client).retrieve(store=..., document=..., sub_query=query)` 호출
3. `AnswerGenerator(client).generate(retrieval=result)` 호출
4. `Answer`와 retrieved 노드 메타데이터를 합쳐 응답

---

## 클라이언트 UI 사양

### 사이드바 항목 추가

[client/src/components/ActivitySidebar.tsx](../../client/src/components/ActivitySidebar.tsx)에 다음을 추가:

- `id: "pdf"`, `label: "pdf"`, `Icon: IconPdf`
- `ActivityView` 타입에 `"pdf"` 합집합 추가

### PdfView 화면 구성

세로로 3개 섹션:

```
┌───────────────────────────────┐
│ [드래그앤드랍 zone]            │  ← .pdf만 허용. 클릭으로도 파일 선택 가능
├───────────────────────────────┤
│ [업로드된 PDF 리스트]          │  ← 각 행: 파일명, indexed 여부, [Index] 버튼
│  - file1.pdf  ✓ indexed       │
│  - file2.pdf  [Index]         │
│  - file3.pdf  [indexing..]    │  ← 인덱싱 중 비활성화
├───────────────────────────────┤
│ 선택된 문서: file1.pdf         │  ← 행 클릭 시 선택. indexed만 선택 가능
│ [질문 입력]              [Ask] │
│                               │
│ 답변:                         │
│ ... LLM 답변 ...              │
│ 인용:                         │
│  - node abc / pages 5-7       │
│  - ...                        │
└───────────────────────────────┘
```

### 상태 관리

`PdfView` 내부에 다음 React state:

```ts
type PdfItem = {
  doc_id: string;
  filename: string;
  size_bytes: number;
  indexed: boolean;
  page_count?: number;
};

const [items, setItems] = useState<PdfItem[]>([]);
const [indexingDocIds, setIndexingDocIds] = useState<Set<string>>(new Set());
const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
const [query, setQuery] = useState("");
const [answer, setAnswer] = useState<AnswerResponse | null>(null);
const [asking, setAsking] = useState(false);
```

**Index 버튼 비활성화 규칙** (요청 사양 "indexing 중에는 indexing.."):
- `indexingDocIds`에 어떤 `doc_id`라도 있으면 모든 행의 'Index' 버튼이 비활성화되고 라벨이 `"indexing.."`로 바뀐다.
- 즉 동시 인덱싱 1건만 허용 — 서버 잠금 없이 UI만으로 제어.

### 드래그앤드랍

`onDragOver` / `onDrop` 핸들러로 `.pdf` mime만 허용. 여러 파일 동시 업로드 시 순차로 `/api/pdf/upload` 호출. 업로드 끝나면 리스트 새로고침.

---

## 경계와 도메인 타입 정합 (CLAUDE.md)

새 경계 두 곳:

1. **`/api/pdf/upload` 핸들러**: HTTP multipart → 디스크에 저장 + `PdfItem` 메타데이터로 변환. 여기서만 mime/확장자 검증.
2. **`AnswerGenerator.generate`**: LLM 응답 JSON → `Answer` Pydantic. 인용된 `node_id`가 retrieval의 노드 집합에 있는지 검증.

도메인 본체는 모두 `RetrievalResult`, `Answer` 같은 도메인 타입을 받고 반환한다. 라우터/뷰 코드에 isinstance, regex, 내부 validate 없음.

---

## 미해결 / 차후

- **인덱싱 진행률**: 현재는 동기 응답. 큰 PDF는 응답이 길어 UI가 멍해 보임. SSE로 phase별 진행 push는 차후.
- **doc 삭제 & 재인덱싱**: 첫 PR에서는 안 만든다.
- **다중 문서 질의**: 사용자 요구 범위 밖. 차후 라우팅 레이어가 필요.
- **PDF 텍스트 미리보기**: 검색 결과 인용을 클릭하면 페이지 텍스트를 보이는 UI는 차후.
- **답변 토큰 초과**: 선택 노드가 너무 많을 때의 truncation 정책. PoC에서는 그대로 던지고 OOM이면 사용자에게 에러 노출.
