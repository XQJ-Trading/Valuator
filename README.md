# Valuator - AI-Powered React Agent Platform

AI 에이전트를 활용한 실시간 분석 및 문제 해결 플랫폼입니다.

## 🏗️ 프로젝트 구조

```
Valuator/
├── server/                     # 백엔드 서버
│   ├── core/                   # AI Agent 핵심 도메인 로직
│   │   ├── agent/              # AI 에이전트 구현
│   │   ├── models/             # LLM 모델 연동
│   │   ├── react/              # ReAct 엔진
│   │   ├── tools/              # 도구 구현
│   │   ├── examples/           # 예제 코드
│   │   └── utils/              # 유틸리티
│   ├── repositories/           # 데이터 저장소 패턴
│   ├── adapters/              # 외부 시스템 어댑터
│   ├── services/              # 비즈니스 로직 서비스
│   │   └── session/           # 세션 관리 서비스
│   └── main.py                # FastAPI 서버 진입점
├── client/                    # 프론트엔드 (Vue.js)
│   ├── src/                   
│   │   ├── components/        # Vue 컴포넌트
│   │   ├── pages/             # 페이지 컴포넌트
│   │   ├── composables/       # Vue Composables
│   │   ├── router/            # 라우터 설정
│   │   ├── styles/            # 스타일 변수
│   │   ├── types/             # TypeScript 타입 정의
│   │   └── utils/             # 유틸리티 함수
│   ├── package.json
│   └── vite.config.ts         # Vite 설정
├── docs/                      # 문서
│   └── ADR/                   # 아키텍처 결정 기록
└── logs/                      # 로그 및 세션 데이터
```

## 🚀 시작하기

### 백엔드 설정

1. **의존성 설치**
   ```bash
   pip install -r requirements.txt
   ```

2. **환경 변수 설정**
   
   `.env` 파일 생성 후 다음 설정:
   
   ```bash
   # Google API Key (필수)
   GOOGLE_API_KEY=your_google_api_key_here
   
   # 사용할 모델 선택 (Gemini 3.0 권장)
   AGENT_MODEL=gemini-3-pro-preview
   # 또는: gemini-3-flash-preview
   
   # 지원 모델 목록
   SUPPORTED_MODELS=gemini-3-pro-preview,gemini-3-flash-preview
   
   # 참고: thinking_level은 API 요청 파라미터로 전달합니다 (환경 변수 아님)
   ```

3. **서버 실행**
   ```bash
   python3 -m uvicorn server.main:app --reload --port 8001
   ```

### 프론트엔드 설정

1. **의존성 설치**
   ```bash
   cd client
   npm install
   ```

2. **개발 서버 실행**
   ```bash
   npm run dev
   ```

## 📋 기능

- **ReAct Engine**: Reasoning + Acting 패턴으로 문제 해결
- **다양한 도구**: 웹 검색, 코드 실행, 파일 시스템, 금융 데이터 분석, Deep Search
- **실시간 스트리밍**: Server-Sent Events를 통한 실시간 응답
- **세션 관리**: 대화 기록 저장 및 조회 (파일/MongoDB)
- **모델 선택**: Gemini 3.0 모델 지원
- **🆕 Gemini3 Direct API**: Google Generative AI SDK 직접 사용
- **🆕 Thinking Level**: Gemini3의 추론 깊이 제어 (high/low)
- **Task Rewrite**: LLM을 활용한 작업 재작성 기능

## 🛠️ 아키텍처

### 백엔드 아키텍처

- **server/core**: AI Agent의 핵심 비즈니스 로직
  - 도메인 모델 (Agent, Tools, Models)
  - ReAct 엔진 구현
  - LLM 연동 및 도구 관리
  - 예제 코드 및 데모
  
- **server/repositories**: 데이터 저장소 패턴
  - 파일 기반 저장소
  - MongoDB 저장소 (선택사항)
  
- **server/adapters**: 외부 시스템 연동
  - 히스토리 관리
  - API 어댑터
  
- **server/services**: 비즈니스 로직 서비스
  - 세션 관리 (생성, 실행, 상태 관리)
  - 세션 러너 및 서비스 레이어

### 프론트엔드 아키텍처

- **Vue 3 + Composition API + TypeScript**
- **실시간 채팅 인터페이스**
- **히스토리 관리**
- **세션 관리**
- **라우팅 시스템**
- **반응형 디자인**

## 🔧 개발 가이드

### 새로운 도구 추가

1. `server/core/tools/` 에 새 도구 클래스 생성
2. `BaseTool` 클래스 상속
3. `AIAgent`에 도구 등록

### 새로운 모델 추가

1. `server/core/models/` 에 새 모델 클래스 생성
2. `BaseModel` 인터페이스 구현
3. 설정에서 모델 선택 가능

## 🆕 Gemini3 Direct API 기능

### 개요

LangChain 래퍼 대신 Google Generative AI SDK를 직접 사용하여 Gemini3의 최신 기능을 활용합니다.

### 주요 이점

- ✅ **Thinking Mode 지원**: Gemini3의 사고 과정 활성화
- ✅ **최신 기능 즉시 사용**: Google API 업데이트 즉시 반영
- ✅ **더 나은 제어**: 직접 API 호출로 세밀한 제어
- ✅ **성능 향상**: 래퍼 레이어 제거로 지연 시간 감소
- ✅ **완전한 호환성**: 기존 LangChain 인터페이스와 호환

### 설정 방법

1. **환경 변수 설정** (`.env` 파일):
   ```bash
   # Gemini3 모델 사용
   AGENT_MODEL=gemini-3-pro-preview
   ```

2. **API 요청에서 Thinking Level 설정**:
   Thinking Level은 각 API 요청의 파라미터로 전달합니다:
   
   ```json
   POST /api/v1/sessions
   {
     "query": "복잡한 문제를 분석해주세요",
     "model": "gemini-3-pro-preview",
     "thinking_level": "high"  // 또는 "low", null
   }
   ```
   
   **Thinking Level 옵션** (Gemini 3.0 전용):
   - `high`: 깊은 추론 (복잡한 작업에 적합, 느림)
   - `low`: 빠른 응답 (간단한 작업에 적합, 빠름)
   - `null` 또는 생략: Thinking Level 비활성화 (기본 동작)

### 아키텍처

```
┌─────────────────────┐
│   GeminiModel       │
├─────────────────────┤
│ GeminiDirectModel   │
│ (Direct SDK)        │
│ - thinking_level    │
│ - 최신 기능 지원     │
└─────────────────────┘
```

### 관련 문서

- [마이그레이션 가이드](docs/GEMINI3_DIRECT_API_MIGRATION.md)
- [구현 계획](docs/PLAN_gemini3_direct_api.md)
- [Thinking 파라미터 조사](docs/FINDINGS_thinking_parameter.md)

## 📝 라이센스

이 프로젝트는 MIT 라이센스 하에 있습니다.
