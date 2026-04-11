# SubjectContext 개선 플랜 (파일 분리 + 구조 정리)

이 문서는 [subject-context-plan.md](./subject-context-plan.md)·[architecture.md](./architecture.md)의 1차 설계를 전제로, **도메인 배치·이름·데이터 정합성**을 다듬는 후속 플랜이다. 구현 시 본 문서와 기존 플랜을 함께 본다.

---

## 1. 배경

- `company.py`는 이미 **회사·상장·Subject 해석** 책임이 크다. 시세 스냅샷 타입까지 한 파일에 두면 **응집도·검색·리뷰**가 나빠진다.
- “온톨로지 노드명”(`StockPrice` 등)과 **도메인 스냅샷** 이름이 겹치면, 이후 시계열·KG 연동 시 혼동된다.
- `subjects` 튜플과 `subject_contexts` 튜플을 **순서만으로 대응**시키면, 일부 subject 스킵 시 **잘못된 매핑** 위험이 있다.

---

## 2. 목표

1. **파일 분리**: 스냅샷 전용 모듈로 타입을 모은다. `company.py`는 `Subject`/`Listing` 등 기존 책임만 유지한다.
2. **안정적 식별**: 컨텍스트는 **subject(또는 listing) 식별자로 조회** 가능한 구조로 둔다.
3. **실패 가시성**: fetch 실패·누락을 모델이 추측하지 않도록 프롬프트에 **한 줄 요약**을 남긴다.
4. **프롬프트 길이 정책**: `[SUBJECT_CONTEXT]`는 **절대 잘리지 않는다**는 규칙을 코드·주석에 명시한다.
5. **진실 공급원 단일화**: `QueryAnalysis` vs `TaskContext` 중 **어느 쪽이 canonical인지** 한 가지로 정한다.
6. **경계 교체 용이**: yfinance ↔ KIS 등은 **경계 모듈**에서만 바꾸고, 상위는 동일 타입을 유지한다.

---

## 3. 파일·모듈 구조 (제안)

| 경로 | 역할 |
|------|------|
| `domain/subject_snapshot.py` (신규) | 불변 값 객체: `SecurityInfo`, `SubjectMarketSnapshot`(또는 동등 이름), `SubjectIndicator`, **`SubjectContext`** 등. **파일명은 “회사”가 아니라 “주제별 시장 스냅샷”에 맞춘다.** |
| `domain/subject_context.py` (신규) | `fetch_subject_contexts` — 경계: 외부 API 호출 → 위 타입으로 변환. yfinance/KIS 구현은 이 파일 또는 `domain/boundary/` 하위로만 제한. |
| `domain/company.py` | **변경 없음** 또는 `SubjectContext` 관련 import만 **다른 모듈로부터 re-export**할지 여부는 팀 선호에 따름(권장: re-export 없이 `subject_snapshot` 직접 import). |

**이름 규칙**

- 온톨로지 `StockPrice` 노드와 구분하려면, 스냅샷 쪽은 예: **`ListedQuote`** / **`SubjectQuote`** / **`SubjectMarketSnapshot`** 중 하나로 고정한다. (플랜 작성 시점 기준 권장: **`SubjectMarketSnapshot`** — 가격·통화·시장 한 덩어리임이 드러남.)
- `Indicator`도 충돌 여지가 있으면 **`SubjectValuationMetrics`** 등으로 좁히거나, 모듈이 `subject_snapshot`이면 `Indicator` 단독 이름도 허용 가능하나 **import 경로로 구분**한다.

---

## 4. 데이터 모델 (정합성)

### 4.1 식별자 기반 보관

- **금지**: `tuple[Subject, ...]` 순서와 `tuple[SubjectContext, ...]` 순서만으로 zip.
- **권장**:
  - `SubjectContext`에 **`subject_company_id`** 또는 **`listing_id`**(둘 중 하나를 필수 stable key로 채택)를 넣거나,
  - 상위에서 `dict[str, SubjectContext]` — 키는 `company_id` 또는 `listing_id`로 통일.

프롬프트 문자열 생성 시: `query_intent.subjects`를 순회하며 **키로 lookup**해 한 줄씩 출력; 없으면 “누락” 분기.

### 4.2 실패·스킵 규약

- Listing 없음 / fetch 실패: 해당 키에는 엔트리가 없거나, **별도 `SubjectContextFetchReport`**(성공 수·실패 사유 요약)를 `QueryAnalysis`에만 둘 수 있다.
- `[SUBJECT_CONTEXT]` 블록 상단 또는 하단에 고정 한 줄 예:  
  `snapshot_status: ok | partial | unavailable` 및 `missing: [...]` (선택).

---

## 5. 진실 공급원 (QueryAnalysis vs TaskContext)

택일 후 문서에 고정:

- **안 A**: `QueryAnalysis.subject_contexts`만 채우고, `build_task_context`에서 **복사**해 `TaskContext`에 넣는다. 디버깅 시 “분석 스펙”과 “실행 시점 컨텍스트”가 동일 스냅샷을 가리킨다.
- **안 B**: 스냅샷은 `TaskContext`에만 두고, `QueryAnalysis`에는 **요약 필드만**(예: `has_subject_snapshot: bool`) — 직렬화 요구가 없을 때 단순.

권장: **안 A** — 세션 로그·재현에 `QueryAnalysis`가 남는 편이 유리하다. 중복이 싫으면 `TaskContext`가 `query_analysis` 참조만 하고 스냅샷은 `query_analysis`에서 읽기만 하는 **파생 뷰**도 가능(구현 복잡도 trade-off).

---

## 6. 프롬프트 (`prompts.py`)

1. `subject_context_text(ctx)`는 **`ctx.subject_contexts` + subjects 순회**로 생성.
2. **`build_step_prompt`에서 `[SUBJECT_CONTEXT]`를 `sections`의 맨 앞에 넣는 것은 유지**하되, 전체 길이 제한 로직이 생기거나 생길 경우:
   - **정책**: `[SUBJECT_CONTEXT]`는 truncate 대상에서 제외하고, `[CHILD_OUTPUTS]` 등 다른 블록부터 줄인다.
   - 구현 시 주석 한 줄로 고정.

---

## 7. 경계: 스냅샷 공급자 (선택, 얇게)

- 프로토콜 또는 단일 함수 타입: `Callable[[Subject, str], SubjectContext | None]` 수준으로 충분.
- 기본 구현: yfinance. 대체: KIS REST 클라이언트. **상위 레이어는 프로토콜만 안다.**

---

## 8. 구현 순서 (권장)

1. `domain/subject_snapshot.py`에 타입 정의 (이름은 §3에 맞춤).
2. `domain/subject_context.py`에 `fetch_subject_contexts` + 식별자 맵 또는 컨텍스트에 키 필드.
3. `domain/query.py` / `valuator/core/context.py`에 필드 추가 — **§5에서 선택한 진실 공급원**에 맞춤.
4. `context_builder.py` 전달.
5. `prompts.py`: `subject_context_text` + §6 길이 정책 주석.
6. 엔트리 스크립트에서 fetch 호출; 가능하면 **한 함수**로 `analysis` 준비까지 묶기(선택).
7. 테스트: 다중 subject 중 일부만 성공 시에도 **틀린 회사에 붙지 않음**을 검증.

---

## 9. 기존 플랜과의 차이 요약

| 항목 | 기존 subject-context-plan | 본 refinement 플랜 |
|------|---------------------------|---------------------|
| 타입 위치 | `domain/company.py`에 추가 | **`domain/subject_snapshot.py` (분리)** |
| 컨텍스트 나열 | `tuple` 병렬 | **키 기반 dict 또는 컨텍스트에 stable id** |
| 실패 | 조용히 skip | **상태 한 줄 + 선택적 missing 목록** |
| 프롬프트 길이 | “맨 앞이라 안 잘림” 가정 | **명시적 비-truncate 정책** |

---

## 10. 의도적으로 하지 않는 것

- 대규모 registry / DI 프레임워크.
- 스냅샷에 대한 프로세스 전역 캐시(요청당 1회 원칙 유지).
- `company.py`에 시세 필드 추가(Listing 확장 없음 원칙 유지 시).

---

## 11. 관련 문서

- [subject-context-plan.md](./subject-context-plan.md) — 1차 기능 플랜
- [architecture.md](./architecture.md) — 데이터 흐름
- [krx-kis-ontology-mapping.md](./krx-kis-ontology-mapping.md) — 시세 원천 확장
