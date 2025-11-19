# ADR: Task Rewrite 기능 구현

## Status
✅ **Accepted & Implemented**

## Context

### 비즈니스 요구사항
사용자가 비구조화된 task 텍스트를 구조화된 형식으로 변환하는 기능이 필요했습니다:
- 자유 형식의 task 입력
- LLM을 활용한 자동 구조화
- 변환 이력 저장 및 조회
- 변환 결과 비교 및 재사용

### 기존 아키텍처와의 관계
- 기존 Session 기능과는 독립적인 새로운 기능
- 동일한 저장소 패턴(Repository) 재사용 가능
- 기존 아키텍처 패턴과의 일관성 유지 필요

## Decision

Task Rewrite 기능을 **기존 아키텍처 패턴을 따르면서 독립적인 모듈**로 구현합니다.

### 핵심 아키텍처

```mermaid
graph TB
    subgraph Client["클라이언트 (Vue 3)"]
        TRP["TaskRewritePage<br/>(변환 입력)"]
        TRHP["TaskRewriteHistoryPage<br/>(이력 목록)"]
        TRDP["TaskRewriteDetailPage<br/>(상세 조회)"]
        UTR["useTaskRewrite Composable<br/>(상태 관리)"]
    end

    subgraph API["API 계층"]
        TR["POST /api/v1/task-rewrite<br/>(변환 실행)"]
        TRH["GET /api/v1/task-rewrite/history<br/>(이력 목록)"]
        TRD["GET /api/v1/task-rewrite/{id}<br/>(상세 조회)"]
        TRDel["DELETE /api/v1/task-rewrite/{id}<br/>(삭제)"]
    end

    subgraph Service["서비스 계층"]
        TRS["TaskRewriteService<br/>(비즈니스 로직)"]
        TRLC["TaskRewriteLLMClient<br/>(LLM 호출)"]
        TRP2["TaskRewritePrompts<br/>(프롬프트 관리)"]
    end

    subgraph Repository["저장소 계층"]
        TRR["TaskRewriteRepository<br/>(추상 인터페이스)"]
        FTRR["FileTaskRewriteRepository<br/>(JSON 파일)"]
        MTRR["MongoTaskRewriteRepository<br/>(MongoDB)"]
    end

    subgraph Model["데이터 모델"]
        TRH2["TaskRewriteHistory<br/>(데이터 모델)"]
    end

    TRP -->|변환 요청| TR
    TRHP -->|이력 조회| TRH
    TRDP -->|상세 조회| TRD
    
    TR --> TRS
    TRH --> TRS
    TRD --> TRS
    TRDel --> TRS
    
    TRS --> TRLC
    TRS --> TRR
    TRLC --> TRP2
    
    TRR <|-- FTRR
    TRR <|-- MTRR
    
    FTRR --> TRH2
    MTRR --> TRH2
    TRS --> TRH2
    
    UTR --> TR
    UTR --> TRH
    UTR --> TRD
    UTR --> TRDel
    
    style Client fill:#e1f5ff
    style API fill:#f3e5f5
    style Service fill:#e8f5e9
    style Repository fill:#fff3e0
    style Model fill:#fce4ec
```

### 1. 레이어 구조

#### Service Layer - TaskRewriteService
```python
# 비즈니스 로직 오케스트레이션
class TaskRewriteService:
    - repository: TaskRewriteRepository
    - llm_client: TaskRewriteLLMClient
    
    + rewrite_task(task, model, custom_prompt) -> TaskRewriteHistory
    + get_rewrite(rewrite_id) -> TaskRewriteHistory
    + list_rewrites(limit, offset) -> List[TaskRewriteHistory]
    + delete_rewrite(rewrite_id) -> bool
```

**책임:**
- LLM 호출과 저장소 저장을 조합
- 변환 이력의 CRUD 작업 제공
- 에러 처리 및 로깅

#### LLM Client Layer - TaskRewriteLLMClient
```python
# 독립적인 LLM 클라이언트
class TaskRewriteLLMClient:
    - api_key: str
    - _model_cache: dict[str, ChatGoogleGenerativeAI]
    
    + rewrite_task(task, custom_prompt, model) -> str
    - _get_model(model_name) -> ChatGoogleGenerativeAI
```

**특징:**
- Core 모듈의 LLM 클라이언트와 독립적으로 구현
- 모델 캐싱으로 성능 최적화
- TaskRewritePrompts를 사용하여 프롬프트 포맷팅

**결정 이유:**
- Task Rewrite는 독립적인 기능이므로 Core 모듈에 의존하지 않음
- 향후 다른 LLM 제공자로 전환 시 유연성 확보
- 모델 캐싱으로 반복 호출 시 성능 향상

#### Repository Layer - TaskRewriteRepository
```python
# 추상 저장소 인터페이스
class TaskRewriteRepository(ABC):
    + save_rewrite(history) -> str
    + get_rewrite(rewrite_id) -> TaskRewriteHistory
    + list_rewrites(limit, offset) -> List[TaskRewriteHistory]
    + delete_rewrite(rewrite_id) -> bool
```

**구현체:**
- `FileTaskRewriteRepository`: JSON 파일 기반 (`logs/task_rewrite/`)
- `MongoTaskRewriteRepository`: MongoDB 기반 (컬렉션: `task_rewrite`)

**기존 패턴과의 일관성:**
- `SessionRepository`와 동일한 추상화 패턴
- File/MongoDB 이중 구현으로 유연성 확보
- 환경 설정에 따라 자동 선택

#### Data Model - TaskRewriteHistory
```python
# 데이터 모델
@dataclass
class TaskRewriteHistory:
    rewrite_id: str
    original_task: str
    rewritten_task: str
    model: str
    custom_prompt: Optional[str]
    created_at: datetime
    metadata: Dict[str, Any]
    
    + to_dict() -> Dict
    + from_dict(data) -> TaskRewriteHistory
```

**특징:**
- 직렬화/역직렬화 메서드 제공
- Repository 구현체와 독립적인 데이터 모델

### 2. API 엔드포인트 설계

| 메서드 | 엔드포인트 | 역할 |
|--------|----------|------|
| POST | `/api/v1/task-rewrite` | Task 변환 실행 및 저장 |
| GET | `/api/v1/task-rewrite/history` | 변환 이력 목록 조회 (페이지네이션) |
| GET | `/api/v1/task-rewrite/{rewrite_id}` | 특정 변환 상세 조회 |
| DELETE | `/api/v1/task-rewrite/{rewrite_id}` | 변환 이력 삭제 |

**설계 원칙:**
- RESTful API 패턴 준수
- 기존 Session API와 네이밍 일관성 유지
- 페이지네이션 지원 (`limit`, `offset`)

### 3. 프론트엔드 아키텍처

#### useTaskRewrite Composable
```typescript
// 싱글톤 상태 관리
const rewrites = ref<TaskRewriteHistory[]>([])
const currentRewrite = ref<TaskRewriteHistory | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

export function useTaskRewrite() {
    + rewriteTask(request) -> Promise<TaskRewriteResponse>
    + fetchRewrites(limit, offset, append) -> Promise<TaskRewriteHistoryList>
    + fetchRewriteDetail(rewriteId) -> Promise<TaskRewriteHistory>
    + deleteRewrite(rewriteId) -> Promise<boolean>
}
```

**특징:**
- 싱글톤 패턴으로 전역 상태 관리
- 자동 목록 업데이트 (변환 후 목록에 추가)
- 에러 처리 및 로딩 상태 관리

#### 페이지 구조
- `TaskRewritePage`: Task 입력 및 변환 실행
- `TaskRewriteHistoryPage`: 변환 이력 목록
- `TaskRewriteDetailPage`: 변환 결과 상세 비교

## Consequences

### ✅ 긍정적 결과

1. **아키텍처 일관성**
   - 기존 Session 기능과 동일한 패턴 사용
   - Repository 패턴으로 저장소 교체 용이
   - Service 레이어로 비즈니스 로직 분리

2. **독립성 확보**
   - Core 모듈에 의존하지 않는 독립적인 LLM 클라이언트
   - Task Rewrite 전용 프롬프트 관리
   - 별도 저장소로 데이터 격리

3. **확장성**
   - 새로운 저장소 구현체 추가 용이
   - 다른 LLM 제공자로 전환 가능
   - 커스텀 프롬프트 지원으로 유연성 확보

4. **유지보수성**
   - 명확한 레이어 분리
   - 각 컴포넌트의 책임이 명확함
   - 테스트 용이성 향상

### ⚠️ 트레이드오프

1. **코드 중복 가능성**
   - SessionRepository와 유사한 패턴으로 일부 중복 가능
   - **완화책**: 공통 인터페이스 추상화로 중복 최소화

2. **독립적인 LLM 클라이언트**
   - Core 모듈의 LLM 클라이언트와 중복 구현
   - **완화책**: Task Rewrite는 독립 기능이므로 의도적 분리

3. **저장소 선택 로직**
   - main.py에서 저장소 생성 로직 중복
   - **완화책**: 팩토리 함수로 패턴 통일

## Alternatives

### 1️⃣ Core 모듈의 LLM 클라이언트 재사용 (제거됨)
- 기존 Core 모듈의 LLM 클라이언트를 재사용
- **장점**: 코드 중복 제거
- **단점**: Core 모듈에 의존성 추가, 독립성 저하
- **선택 안 함**: Task Rewrite는 독립 기능이므로 의존성 분리 필요

### 2️⃣ SessionRepository 확장 (제거됨)
- 기존 SessionRepository에 Task Rewrite 기능 추가
- **장점**: 저장소 구현체 재사용
- **단점**: 책임 혼재, 확장성 저하
- **선택 안 함**: Task와 Session은 다른 도메인이므로 분리 필요

### 3️⃣ 단일 저장소 구현 (제거됨)
- File 또는 MongoDB 중 하나만 지원
- **장점**: 구현 단순화
- **단점**: 유연성 저하, 환경별 대응 어려움
- **선택 안 함**: 기존 패턴과의 일관성 및 유연성 확보

**선택한 방식:** 독립 모듈 + 기존 패턴 준수
- TaskRewriteService로 비즈니스 로직 분리
- 독립적인 LLM 클라이언트로 의존성 분리
- Repository 패턴으로 저장소 유연성 확보

## Implementation Details

### 백엔드 레이어 구성

```
server/
├── main.py                              (Task Rewrite API 엔드포인트)
├── services/
│   └── task_rewrite/                    (✅ Task Rewrite 서비스 모듈)
│       ├── __init__.py
│       ├── service.py                   (✅ TaskRewriteService)
│       ├── llm_client.py                (✅ TaskRewriteLLMClient)
│       ├── prompts.py                   (✅ TaskRewritePrompts)
│       └── models.py                    (✅ TaskRewriteHistory)
└── repositories/
    └── task_rewrite_repository.py       (✅ TaskRewriteRepository 구현체)
        ├── TaskRewriteRepository (ABC)
        ├── FileTaskRewriteRepository
        └── MongoTaskRewriteRepository
```

### 구조 설계 원칙

1. **Service 계층 분리**
   - `server/services/task_rewrite/` 디렉토리로 모듈화
   - Session 서비스와 동일한 구조 패턴

2. **Repository 패턴**
   - 추상 인터페이스로 구현체 교체 용이
   - File/MongoDB 이중 구현

3. **독립적인 LLM 클라이언트**
   - Core 모듈과 분리하여 독립성 확보
   - 모델 캐싱으로 성능 최적화

4. **프롬프트 관리**
   - TaskRewritePrompts 클래스로 중앙 관리
   - 커스텀 프롬프트 지원

### 프론트엔드 레이어 구성

```
client/src/
├── composables/
│   └── useTaskRewrite.ts                (✅ 상태 관리)
├── components/
│   └── task-rewrite/
│       ├── ComparisonView.vue           (✅ 비교 뷰)
│       └── RewriteCard.vue              (✅ 이력 카드)
├── pages/
│   ├── TaskRewritePage.vue             (✅ 변환 입력)
│   ├── TaskRewriteHistoryPage.vue      (✅ 이력 목록)
│   └── TaskRewriteDetailPage.vue        (✅ 상세 조회)
├── types/
│   └── TaskRewrite.ts                   (✅ 타입 정의)
└── router/
    └── index.ts                         (라우팅 추가)
```

### 주요 구현 특징

1. **싱글톤 상태 관리**
   - `useTaskRewrite` composable에서 전역 상태 관리
   - 변환 후 자동 목록 업데이트

2. **비교 뷰 컴포넌트**
   - 원본과 변환 결과를 나란히 비교
   - 복사 기능 제공

3. **페이지네이션**
   - "더 보기" 버튼으로 추가 로드
   - `append` 모드로 기존 목록에 추가

## Migration Path

### Phase 1: 기본 구현 ✅ 완료
- ✅ TaskRewriteService 구현
- ✅ TaskRewriteRepository (File/MongoDB) 구현
- ✅ TaskRewriteLLMClient 구현
- ✅ TaskRewritePrompts 구현
- ✅ API 엔드포인트 4개 추가
- ✅ 프론트엔드 페이지 및 컴포넌트 구현
- ✅ useTaskRewrite Composable 구현

### Phase 2: 개선 사항 (권장)
- [ ] 프롬프트 템플릿 시스템 (동적 프롬프트 관리)
- [ ] 변환 결과 검증 로직
- [ ] 배치 변환 기능
- [ ] 변환 품질 평가 메트릭

### Phase 3: 고급 기능 (미래)
- [ ] 변환 결과 버전 관리
- [ ] 변환 템플릿 저장 및 재사용
- [ ] A/B 테스트 (다양한 프롬프트 비교)
- [ ] 변환 히스토리 분석 대시보드

## Code Quality Improvements

### Dead Code 제거
- ✅ `_get_task_rewrite_repositories()` 함수 제거 (사용되지 않음)
- ✅ `update_base_prompt()` 메서드 제거 (사용되지 않음)
- ✅ 잘못된 import 경로 수정 (`llm_client.py`)

### 아키텍처 일관성 개선
- ✅ MongoDB 연결 종료 로직 추가 (lifespan shutdown)
- ✅ Import 구조 통일 (`repositories/__init__.py`)

## References

- **Repository Pattern**: Domain-Driven Design
- **Service Layer Pattern**: Clean Architecture
- **RESTful API**: REST API Best Practices
- **Vue Composables**: Composition API Pattern

## Questions & Decisions Log

**Q: 왜 Core 모듈의 LLM 클라이언트를 재사용하지 않나?**
A: Task Rewrite는 독립적인 기능이므로 Core 모듈에 의존성을 추가하지 않기 위해 독립적인 클라이언트를 구현했습니다.

**Q: SessionRepository를 확장하지 않은 이유는?**
A: Task와 Session은 서로 다른 도메인이므로 책임 분리를 위해 별도의 Repository를 구현했습니다.

**Q: 왜 File과 MongoDB 둘 다 지원하나?**
A: 기존 Session 기능과의 일관성을 유지하고, 다양한 환경에서의 유연성을 확보하기 위해 이중 구현을 선택했습니다.

**Q: 프롬프트를 별도 클래스로 관리한 이유는?**
A: 프롬프트 변경이 빈번할 수 있고, 향후 동적 프롬프트 관리가 필요할 수 있어 별도 클래스로 분리했습니다.

---

**Last Updated**: 2025-11-09
**Version**: 1.0.0

