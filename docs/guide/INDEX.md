# Valuator 프로젝트 가이드

LLM 기반 기업 가치 분석 플랫폼. 도메인 질의를 분해하여 다단계 파이프라인으로 분석 보고서를 생성합니다.

## 📚 목차

### 기본
- [프로젝트 개요](01-Overview.md) — 프로젝트 개념과 주요 특징
- [아키텍처](02-Architecture.md) — Plan → Execute → Aggregate → Review 파이프라인

### 핵심 파이프라인 (server/core)
- [핵심 파이프라인 상세](03-Core-Pipeline/index.md)
  - [작업 시스템 (Task & AtomicTask)](03-Core-Pipeline/01-Task-System.md)
  - [스케줄러 (Scheduler)](03-Core-Pipeline/02-Scheduler.md)
  - [계획 (Planning & StepPlanner)](03-Core-Pipeline/03-Planning.md)
  - [에이전트 루프 (Agent Loop)](03-Core-Pipeline/04-Agent-Loop.md)
  - [분해 및 검토 (Decomposition & Gate)](03-Core-Pipeline/05-Decomposition.md)
  - [공유 상태 (SharedState)](03-Core-Pipeline/06-Shared-State.md)

### 보조 시스템
- [도구 시스템 (Tools)](04-Tools.md)
- [LLM 모델 (Models)](05-Models.md)
- [서버 API](06-Server-API.md)

## 🎯 빠른 시작

### 핵심 개념 3가지

1. **Task** — 작업의 원자 단위. 분해되거나 실행됨
2. **Scheduler** — 작업 의존성 추적 및 우선순위 관리
3. **Pipeline** — 계획 → 에이전트 실행 → 분해 → 검토 → 최종화

### 코드 흐름

```
query
  ↓ [Planning] → TaskDecision (분해/실행/집계)
  ↓ [Agent Loop] → Task 선택 및 실행
  ↓ [Scheduler] → 의존성 해석, 상태 관리
  ↓ [Decomposition Gate] → 분해 품질 검증
  ↓ [SharedState] → 사실(fact) 발행
  ↓ [Final Output]
```

## 📁 디렉토리 구조

```
valuator/
├── core/              # ⭐ 핵심 파이프라인
│   ├── planning/      # 계획 단계
│   ├── agent/         # 에이전트 루프
│   ├── decomposition/ # 분해/검증
│   ├── scheduler.py   # 스케줄러
│   ├── task.py        # 작업 정의
│   ├── context.py     # TaskContext
│   └── shared_state.py# 공유 상태
├── tools/             # 도구 구현
├── models/            # LLM 인터페이스
└── runtime.py         # 도구 레지스트리

server/
├── main.py            # FastAPI 앱
├── chat_api.py        # 채팅 엔드포인트
└── session_viewer_api.py # 세션 조회
```

## 🔍 각 문서의 역할

| 문서 | 대상 | 내용 |
|------|------|------|
| Overview | 전체 | 프로젝트 목표, 파이프라인 개요 |
| Architecture | 아키텍트 | 시스템 설계, 데이터 흐름 |
| Core Pipeline | 엔지니어 | 각 단계의 구현 상세 (가장 중요) |
| Tools | 확장 개발자 | 새 도구 추가 방법 |
| Models | 모델 담당자 | LLM 통합 방법 |
| Server API | 프론트엔드 | API 엔드포인트, 데이터 형식 |
