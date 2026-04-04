# 공유 상태 (SharedState)

`SharedState`는 에이전트 내의 모든 작업(Task)이 접근할 수 있는 **중앙 집중형 팩트(Fact) 저장소**입니다. 작업 간 직접적인 정보 전달을 금지하고, 모든 데이터 교환은 이 저장소를 통해서만 이루어집니다.



## 1. 데이터 구조: Fact

모든 정보는 `Fact`라는 단위로 저장되며, 단순한 값을 넘어 출처와 시간 정보 등 풍부한 메타데이터를 포함합니다.

```python
@dataclass(frozen=True)
class Fact:
    key: str                    # 식별자 (예: "apple_revenue_2024")
    value: Any                  # 실제 데이터
    source_task_id: str         # 팩트를 생성한 작업 ID
    grounded: bool              # 근거 여부 (도구 결과 기반이면 True, LLM 추론이면 False)
    source_urls: tuple[str, ...] # 출처 URL 리스트
    
    # 시간 관련 메타데이터
    as_of_utc: str              # 데이터 기준 시점
    time_scope: str             # 시간 범위 (예: "FY2024")
    target_start: str           # 데이터 유효 시작일
    target_end: str             # 데이터 유효 종료일
    
    published_at: str           # 저장소 발행 시각
```

---

## 2. 팩트 발행 및 조회 흐름

### 발행 (Publishing)
작업이 완료되거나 중간 결과를 집계할 때 `AGGREGATE` 액션을 통해 팩트를 저장합니다.

1.  **계획 단계:** LLM이 발견된 정보와 출처를 정리하여 `TaskDecision`에 포함합니다.
2.  **반영 단계:** 스케줄러가 `SharedState.publish()`를 호출하여 저장소에 기록합니다.

```python
# Scheduler 내 반영 로직 예시
shared.publish(
    key="market_cap",
    value=3_200_000_000_000,
    grounded=True,
    source_urls=("https://finance.yahoo.com/quote/AAPL",),
    # ... 기타 시간 메타데이터
)
```

### 조회 (Querying)
플래너가 다음 단계를 결정하기 위해 컨텍스트를 구성할 때 저장된 팩트를 읽어옵니다.

* **`get(key)`**: 특정 키에 해당하는 값 반환.
* **`find_all()`**: 현재까지 수집된 모든 팩트를 딕셔너리 형태로 반환.
* **`view_for(task_id)`**: 특정 작업 시점에서 유효한 팩트들만 필터링된 뷰(View)를 제공.

---

## 3. 핵심 메커니즘

### 팩트 유효성 및 덮어쓰기
동일한 `key`로 새로운 팩트가 발행되면 **마지막에 발행된 값이 이전 값을 덮어씁니다.** 이는 최신 정보가 우선시되는 정책을 따릅니다.

### 암시적 집계 (Implicit Aggregation)
하위 작업들이 모두 완료되고 정보를 반환할 때, 에이전트는 자식 작업들이 생산한 팩트들을 자동으로 병합(Merge)하여 부모 작업의 컨텍스트에 주입합니다.

### 프롬프트 주입
플래너는 수집된 팩트들을 기반으로 다음과 같이 프롬프트를 구성합니다.
> **지금까지 발견된 사실들:**
> - apple_revenue: 195B (근거: 있음, 출처: SEC 10-K)
> - analysis_summary: "성장세 유지" (근거: 없음, LLM 추론)

---

## 4. 설계 원칙 (Design Principles)

1.  **유일한 정보 경로 (Single Source of Truth):**
    작업은 다른 작업의 내부 상태를 직접 참조할 수 없습니다. 오직 `SharedState`에 발행된 팩트만을 신뢰합니다.
2.  **메타데이터 보존 (Preserve Provenance):**
    "무엇이" 맞는가보다 "왜" 맞는가가 중요합니다. 모든 팩트는 `source_urls`와 `grounded` 플래그를 통해 검증 가능해야 합니다.
3.  **불변성 (Immutability):**
    한 번 생성된 `Fact` 객체는 수정될 수 없습니다(`frozen=True`). 데이터가 변경되어야 한다면 새로운 `Fact`를 발행하여 교체해야 합니다.

---

## 5. 시간 범위(Temporal) 처리 예시

질의 내용에 따라 팩트의 유효 범위를 엄격하게 관리합니다.

```python
# "2024년 수익" 질의 처리 시
shared.publish(
    key="apple_revenue",
    value=195_000_000_000,
    time_scope="FY2024",
    target_start="2024-01-01",
    target_end="2024-12-31"
)
```

이 구조를 통해 에이전트는 서로 다른 시점의 데이터를 혼동하지 않고 정확한 비교 분석을 수행할 수 있습니다. 특히 `grounded` 메타데이터는 최종 답변의 신뢰도를 높이는 결정적인 역할을 합니다.