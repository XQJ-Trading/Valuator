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
│   │   └── utils/              # 유틸리티
│   ├── repositories/           # 데이터 저장소 패턴
│   ├── adapters/              # 외부 시스템 어댑터
│   └── main.py                # FastAPI 서버 진입점
├── client/                    # 프론트엔드 (Vue.js)
│   ├── src/                   
│   │   ├── components/        # Vue 컴포넌트
│   │   ├── pages/             # 페이지 컴포넌트
│   │   └── composables/       # Vue Composables
│   └── package.json
└── logs/                      # 로그 및 세션 데이터
```

## 🚀 시작하기

### 백엔드 설정

1. **의존성 설치**
   ```bash
   pip install -r requirements.txt
   ```

2. **환경 변수 설정**
   ```bash
   cp .env.example .env
   # .env 파일에서 API 키 설정
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
- **다양한 도구**: 웹 검색, 코드 실행, 파일 시스템, 금융 데이터 분석
- **실시간 스트리밍**: WebSocket을 통한 실시간 응답
- **세션 관리**: 대화 기록 저장 및 조회
- **모델 선택**: 다양한 AI 모델 지원

## 🛠️ 아키텍처

### 백엔드 아키텍처

- **server/core**: AI Agent의 핵심 비즈니스 로직
  - 도메인 모델 (Agent, Tools, Models)
  - ReAct 엔진 구현
  - LLM 연동 및 도구 관리
  
- **server/repositories**: 데이터 저장소 패턴
  - 파일 기반 저장소
  - MongoDB 저장소 (선택사항)
  
- **server/adapters**: 외부 시스템 연동
  - 히스토리 관리
  - API 어댑터

### 프론트엔드 아키텍처

- **Vue 3 + Composition API**
- **실시간 채팅 인터페이스**
- **히스토리 관리**
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

## 📝 라이센스

이 프로젝트는 MIT 라이센스 하에 있습니다.
