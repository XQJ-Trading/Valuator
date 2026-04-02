# Research UI Client

루트 `client/` 는 Research UI React 앱입니다.

## 개발

```bash
cd client
npm install
npm run dev
```

- 기본 개발 서버: `http://localhost:5173`
- `/api` 요청은 `http://localhost:8001` 로 프록시됩니다.

## 백엔드

백엔드는 별도로 실행해야 합니다.

```bash
.venv/bin/python -m uvicorn server.main:app --reload --port 8001
```

기본값은 리포지토리 루트 기준 `logs/local`(세션), `logs/session_history`(서버·히스토리)입니다. 다른 위치를 쓰려면 루트 `.env` 에 지정합니다.

```bash
SESSION_DATA_ROOT=/absolute/path/to/session-data
GUIDE_DATA_ROOT=/absolute/path/to/session_history
```
