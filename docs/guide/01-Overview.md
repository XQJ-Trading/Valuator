# 프로젝트 개요

## 🎯 목표

LLM 기반으로 기업의 가치를 분석하는 플랫폼. 사용자의 도메인 질의를 자동으로 분해하고, 다단계 파이프라인을 통해 근거 있는 분석 보고서를 생성합니다.

## 🔄 핵심 파이프라인

```
사용자 질의
   ↓
[계획] Plan — LLM이 할 일 결정 (분해/실행/집계)
   ↓
[실행] Execute — 정해진 작업 수행 (도구 실행, LLM 호출)
   ↓
[집계] Aggregate — 결과를 사실(fact)로 발행
   ↓
[검토] Review — 분해 품질 검증, 필요시 다시 계획
   ↓
최종 보고서
```

## 📊 주요 개념

### 1. 작업 (Task)
- **원자 단위**: 분해 불가능하거나 도구 실행 필요
- **복합 작업**: 자식 작업으로 분해 가능
- **상태**: CREATED → READY → RUNNING → WAITING → DONE / FAILED

### 2. 의존성 관리
- 작업 간 선형/병렬 실행 제어
- 자식 작업들의 시블링 의존성 (예: A 완료 후 B 시작)
- 교착 상태(deadlock) 감지 및 해제

### 3. 공유 상태
- 모든 작업이 접근 가능한 팩트 저장소
- 작업이 발견한 사실(fact)을 다른 작업에서 참조 가능
- 시간 범위, 출처 URL 등 메타데이터 추적

### 4. 도구 (Tool)
- **웹 검색**: Perplexity API
- **재무 데이터**: yfinance (잔액표)
- **SEC 문서**: 10-K, 8-K 등
- **코드 실행**: Python 샌드박스

### 5. 분해 게이트 (Decomposition Gate)
- 과도한 분해 방지
- 분해 품질 평가 (LLM)
- 동적 임계값 조정 (학습)

## 🏗️ 아키텍처 계층

### 경계 (Boundary)
- HTTP 요청/응답 처리
- LLM API 호출
- 파일/YAML 파싱
- **역할**: 검증이 아니라 원시 입력을 도메인 타입으로 변환

### 비즈니스 로직
- Task 상태 관리
- Scheduler 의존성 추적
- Planning 의사 결정
- Decomposition 평가
- **원칙**: 방어적 검증 금지, 타입이 보증이 됨

## 📦 사용 기술

- **Framework**: FastAPI (서버), React (클라이언트)
- **LLM**: Claude API (주), Gemini, OpenRouter (지원)
- **도구**: yfinance, Perplexity, 커스텀 샌드박스
- **데이터**: 세션 파일, Markdown 추적 기록

## 🔌 통합 방식

```
사용자 쿼리 → Server API
         ↓
    [Agent 초기화]
         ↓
    [Loop] 작업 처리
     - Scheduler: 다음 실행할 작업 선택
     - Planner: TaskDecision 생성
     - Gate: 분해 검증
     - Tools: 실행
         ↓
  공유 상태 업데이트
         ↓
   최종 보고서 생성
         ↓
  Session 저장 & 반환
```

## 🚀 주요 진화

**v2.0**: 서브프로세스 기반 코드 실행, 탭별 세션 동기화
