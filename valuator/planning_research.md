# HDPS Planning 리서치 노트 (v2.7)

## 1. 문제 상황 정리
### ReAct 구조적 문제
- ReAct는 세션이 길어질수록 컨텍스트가 고정/비대화되어 제약이 커진다.
- Thought → Action → Observation 루프가 길어지면 프롬프트가 오염되고 역할 경계가 흐려진다.
- 결과적으로 Planner/Executor/Critic 분리가 약해지고, “누가 무엇을 책임지는지”가 불명확해진다.

### 추가 기능 필요
- Top-Down + 계층적(Hierarchy) 문제 분해
- 병렬 실행이 가능한 작업 구조
- 프롬프트 제약을 넘어서는, LLM 지식 기반의 **명시적 계획**과 **명시적 행동**

## 2. Plan이란 무엇인가
Plan은 “미래 행동을 구조화하고, 공유하며, 책임지는 장치”다.

### Plan의 설계 차원
1) 존재 방식: 상태(state) vs 추론(inference)  
2) 대상 범위: reasoning / tool / task  
3) 시간 축: 얼마나 먼 미래까지 명시할 것인가  
4) 강제성: 누가 책임지고, 실패 시 어떻게 재계획할 것인가

### Plan Representation 핵심
- 단위: Task node (id, title, deps, outputs, acceptance)
- 구조: DAG (top-down 분해)
- 저장: 파일 시스템 상태(/plan/**)
- 가시성: 시스템+인간 모두 읽을 수 있음
- 지속성: revision, snapshot, append-only 로그
- 실행성: 병렬 실행/실패 재시도/재계획 가능

## 3. Approach 레이어
### L1: Cognitive Scaffolding
- CoT / ToT / GoT 등 “추론 구조” 최적화

### L2: Control Loop
- ReAct, Plan-and-Solve, ReWOO 등 “다음 행동 결정” 구조

### L3: System Architecture
- 상태를 외부화하고, 역할 분리를 강제하는 운영 구조

## 4. 주요 아키텍처 비교
### Plan-and-Solve (프롬프트 기법)
- Plan 단계에서 서브문제를 나누고, Solve 단계에서 순차 해결
- 장점: 단순하고 안정적
- 한계: 실행 스케줄/외부 도구/병렬 처리 부재

### Plan-and-Execute (시스템 아키텍처)
- Planner: 목표 → 태스크 그래프 생성
- Executor: 태스크 실행
- Critic: 결과 검수 및 승격
- Replanner: 실패 시 재분해/재시도/스위치
- 장점: 실행/검수/재계획 분리 가능, 병렬화 가능

### Tree-of-Thoughts (ToT)
- 상위 노드: 전략, 하위 노드: 실행 단위
- 각 노드에서 self-eval로 분기/백트래킹
- 장점: 탐색력, 유연한 전환
- 단점: 느림, 토큰 비용 증가

### Graph-of-Thoughts (GoT)
- ToT를 DAG/그래프로 확장
- 노드 간 공유/재사용 가능
- 메타 그래프 레이어로 관리 가능

### ReWOO (Reasoning Without Observation)
- 도구 호출 순서를 먼저 확정하고, 실행은 후처리
- 장점: 빠름, 제어 단순
- 단점: 실행 피드백 반영 어려움

## 5. HDPS에 맞는 결정
### Core 선택: Plan-and-Execute
- Planner/Executor/Critic 분리를 시스템 레벨에서 강제
- 계획은 /plan에 고정된 상태로 저장
- 실행은 /execution에서만 기록
- 검수는 /critique에서만 기록

### Cognitive 기법은 보조 레벨
- ToT/GoT/ReWOO는 “Planner의 내부 전략”으로만 사용
- 시스템 전체 운영 규칙으로 강제하지 않음

## 6. HDPS 설계 매핑
- Planner: /plan/active/decomposition.json 생성
- Executor: /execution/run_logs + /execution/outputs/T-xxxx 기록
- Critic: /critique/reports, PASS 시 /context/index.json 승격
- Replanner: 실패 누적 → revision++ 또는 snapshot + major bump
- Sessions: 입력/출력 뷰 전용, 내부 로그/중간 산출물 비노출

## 7. 병렬 실행 설계
- Plan은 DAG 구조로 병렬 실행 가능하게 설계
- Executor는 독립된 task_id 단위 실행
- 병렬 실행 결과는 outputs/T-xxxx/로 격리
- 실패 시 특정 task만 재실행 가능

## 8. 최종 결론
HDPS는 L3(System Architecture)에서 Plan-and-Execute를 기본 구조로 채택한다.  
L1/L2는 Planner 내부 전략으로만 활용하고, 시스템 상태는 파일로 고정한다.

## 9. 참고
- https://www.wollenlabs.com/blog-posts/navigating-modern-llm-agent-architectures-multi-agents-plan-and-execute-rewoo-tree-of-thoughts-and-react
