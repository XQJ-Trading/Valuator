# 분해 및 검증 (Decomposition & Gate)

에이전트가 제안한 작업 분해(Decomposition)의 품질을 평가하고, 불필요하거나 과도한 분해를 차단하여 시스템의 안정성을 확보하는 단계입니다.



## 1. GateController: 시스템의 수문장

`GateController`는 모든 `DECOMPOSE` 결정에 대해 3단계 검증을 수행합니다. 검증에 실패하면 에이전트는 분해 대신 다른 전략(직접 실행 등)을 세워야 합니다.

```python
class GateController:
    async def gate(self, task: Task, decision: TaskDecision, ctx: TaskContext) -> TaskDecision:
        if not self._config.enabled or decision.action != Action.DECOMPOSE:
            return decision 
        
        # 1단계: Pre-filter (규칙 기반 검사)
        filter_result = pre_filter(task, decision, self._config)
        if filter_result.verdict == FilterVerdict.REJECT:
            return self._create_rejection_decision(filter_result.reason)
        
        # 2단계: LLM Critic (의미론적 품질 평가)
        critique = await self._critic.evaluate_decomposition(task, decision, ctx)
        
        # 3단계: Dynamic Threshold (동적 임계값 적용 및 학습)
        threshold = self._tracker.current_threshold()
        if critique.quality_score >= threshold:
            self._tracker.record_success() # 통과 시 임계값 미세 조정 (더 엄격하게)
            return decision
        else:
            self._tracker.record_failure() # 거절 시 임계값 미세 조정 (더 관대하게)
            return self._create_rejection_decision(critique.reason)
```

---

## 2. 3단계 검증 프로세스

### **Step 1. Pre-filter (하드웨어 규칙)**
비용이 들지 않는 빠른 검사입니다. 시스템 리소스 보호를 위한 '하드 리미트'를 체크합니다.

* **최대 깊이(Max Depth):** 작업이 너무 깊게 계층화되는 것 방지 (예: 10단계 이상 금지).
* **단계 제한(Max Steps):** 한 작업이 너무 많은 시도를 하는 것 방지.
* **자식 수 제한(Max Children):** 한 번에 너무 많은 하위 작업으로 쪼개는 것 방지.

### **Step 2. LLM Critic (소프트웨어 지능)**
LLM이 제안된 분해안이 원래의 목적에 부합하는지, 논리적 비약은 없는지 평가합니다.
* **평가 항목:** "이 분해가 목표 달성에 필수적인가?", "하위 작업 간의 중복은 없는가?"
* **출력:** 0.0 ~ 1.0 사이의 품질 점수 및 개선 권고안.

### **Step 3. Threshold Adjustment (적응형 학습)**
시스템의 '깐깐함'을 실시간으로 조정합니다.
* **성공 시:** 임계값을 높여(`+learning_rate`) 더 고품질의 분해만 허용하도록 유도합니다.
* **거절 시:** 임계값을 낮춰(`-learning_rate`) 작업 진행이 막히지 않도록 유연성을 부여합니다.

---

## 3. 거절 및 회복 로직 (Recovery)

게이트에 의해 분해가 거절되면 에이전트는 **"분해 금지"** 상태로 다시 계획을 세웁니다.

1.  **거절 통보:** `Gate`가 `REJECT`와 함께 이유(Reason)를 반환합니다.
2.  **재쿼리(Re-query):** `StepPlanner`가 해당 작업에 대해 `allow_decompose=False` 옵션을 받아 다시 생각합니다.
3.  **대안 선택:** 에이전트는 분해하지 않고 도구를 직접 실행(`EXECUTE`)하거나, 지금까지의 정보로 결과를 요약(`AGGREGATE`)하는 방향으로 선회합니다.

---

## 4. 주요 설정 (GateConfig)

시스템 환경에 따라 게이트의 엄격도를 조절할 수 있습니다.

| 설정 항목 | 기본값 | 설명 |
| :--- | :--- | :--- |
| `max_depth` | 10 | 작업 계층의 최대 허용 깊이 |
| `max_steps_per_task` | 20 | 단일 작업 내 최대 허용 시도 횟수 |
| `initial_threshold` | 0.7 | Critic 점수의 초기 통과 기준 |
| `learning_rate` | 0.05 | 결과에 따른 임계값 조정 폭 |
| `critic_enabled` | True | LLM을 이용한 정밀 평가 사용 여부 |

---

## 5. 실행 예시 흐름

1.  **계획:** 에이전트가 "삼성전자 주가 분석" 작업을 5개로 쪼개겠다고 결정합니다.
2.  **필터:** 자식 수가 5개이므로 통과합니다.
3.  **비판:** Critic이 분석하니 "3번과 4번 작업이 중복됨"이라며 **0.5점**을 줍니다.
4.  **판단:** 현재 임계값이 **0.7**이므로 **거절(Reject)** 됩니다.
5.  **수정:** 에이전트는 "중복된 분석을 합쳐서 직접 도구를 호출해 처리하자"고 계획을 변경합니다.