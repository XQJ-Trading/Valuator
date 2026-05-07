## System Boundaries

경계(boundary)는 외부 입력이 시스템에 진입하거나 떠나는 지점이다.
외부 I/O를 직접 다루는 코드(HTTP 요청/응답, LLM API 호출, 외부 API 호출, 파일/YAML 파싱)가 경계이며, 나머지는 모두 business logic이다.
경계의 역할은 검증이 아니라 **원시 입력을 도메인 타입으로 변환하는 것**이다. 변환이 완료되면 타입의 존재 자체가 검증 완료의 증거이므로, 경계 이후에는 재검증하지 않는다.

## Planning

요청을 액면 그대로 실행하지 않는다. 숨겨진 가정, 누락, 정보 공백을 먼저 드러낸다.
접근법 2-3개와 트레이드오프를 제시한 뒤, 승인을 받고 구현한다.
요청받지 않은 동작은 구현하지 않는다.

## Coding Principles

- 가장 단순한 동작 해법을 선택한다. 추가보다 제거/단순화를 우선한다.
- 함수는 한 가지 일만 한다. 제어 흐름은 평탄하게. 깊은 중첩과 헬퍼 체인 금지.
- early return. 사이드이펙트와 I/O 순서를 바꾸지 않는다.
- fail fast. 에러를 전파한다. 예외를 삼키거나 fallback 값으로 마스킹하지 않는다.
- 타입: 경계에서 Pydantic으로 변환. 내부에서 isinstance 등 방어적 타입 체크 금지. 단일 분기를 제거하기 위해 타입을 추가하지 않는다 — 분기가 단순하면 분기가 타입보다 낫다.
- 주석은 WHY만. 요구사항이 불분명하거나 복잡도가 증가하면 멈추고 확인을 요청한다.
- 함수를 한눈에 이해할 수 없다면 설계가 잘못된 것이다.

## Prohibited Patterns — Highest Priority

Business logic 내부에 "코드를 위한 코드"(insurance code, formalistic checks, rule-based branching)를 두지 않는다.
이런 패턴은 경계에서만 허용된다. 예외 시 한 줄 정당화 주석을 단다.

- ensure: 경계에서 validate + fail 용도로만 허용
- validate: 경계에서 1회만. 내부 재검증 금지
- normalize / sanitize: 경계에서 입력 수신 직후 1회만. 내부 금지
- check (check_exists, check_permission 등): 경계에서 수락/거부만. 내부 반복 체크 금지
- rule-based branching: 도메인 타입, 값 객체, 명시적 상태로 대체. "kind" 분류는 경계에서만
- regex: 경계에서 파싱/검증 용도로만. 내부 포맷 기반 분기 금지
- assert (런타임 보험), coerce/cast, 내부 파싱, get_or_default 에러 마스킹: 명확한 경계 정의 없이 내부에서 값을 교정하는 모든 패턴 금지

### Decision Rule

- "외부 입력을 수락하거나 거절하는 단계인가?" → 경계 로직 (validate/normalize/sanitize/regex 고려)
- "이미 경계를 통과한 값으로 무엇을 할지 결정하는 단계인가?" → business logic (위 패턴 모두 금지)

### Root Causes — 금지 패턴보다 이것을 먼저 본다

금지 패턴은 증상이다. 근본 원인은 두 가지이며, 상호 의존한다:

**1. 경계 책임 미완결** — 경계가 변환과 거부를 끝까지 하지 않는다.
- 경계의 위치를 결정하지 않았다 → validate/check/ensure가 어디서든 추가된다
- 포맷→의미 변환이 경계에서 완료되지 않는다 → regex와 파싱이 내부로 침투한다
- 경계가 거부를 완결하지 않는다 → 모든 하류가 스스로 방어한다

**2. 도메인 타입 부재** — 도메인 개념이 타입으로 존재하지 않아 보증이 전달되지 않는다.
- 경계가 원시 타입(`str`, `dict`)을 그대로 통과시킨다 → isinstance, 방어적 타입 체크가 퍼진다
- 도메인 개념이 문자열이나 플래그로 표현된다 → rule-based branching

경계가 변환을 완결하려면 변환할 도메인 타입이 있어야 하고,
도메인 타입이 의미 있으려면 경계에서 생성되어야 한다.
금지 패턴을 추가하려는 충동이 들면, "경계와 타입을 어떻게 정의할 것인가"로 전환한다.

## Scope of Application

- 새 코드 또는 명시적 리팩토링: 모든 원칙 적용
- 기존 코드 수정: 변경 범위 내에서 원칙 적용. 접촉한 파일에서 위반을 발견하면 현재 변경의 실현 가능한 범위 내에서 정리한다 (타입 명확화, 검증을 경계로 이동 등). "이 PR은 기능 추가만이다"라는 이유로 원칙 적용을 제한하지 않는다.

## Commands

- Server: `uvicorn server.main:app --reload`
- Client: `cd client && npm run dev`
- Test: `python -m pytest tests/`
- Lint: `ruff check .`
- Format: `ruff format .`
