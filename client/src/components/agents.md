# Developer Tools — 의사결정 기록

## 아키텍처

**서버 변경 없이 구현.**
배포 서버의 기존 `POST /api/fs/create` + `PUT /api/file` 엔드포인트를 클라이언트에서 직접 호출해 로컬 세션을 원격 서버로 복사한다. 새 엔드포인트 불필요.

## 업로드 범위

두 가지 모드:
- **핵심만**: `session.json`, `browse/`, `output/` — 뷰어(browse-outline API)가 실제로 읽는 파일만
- **전체**: `trace/` 제외, 800KB 이하 — trace는 항상 제외 (대용량 실행 로그, 뷰어 불사용)

## 파일 크기 제한 (800KB)

nginx 기본 `client_max_body_size = 1MB`. PUT body = JSON 래퍼 + 파일 content이므로
실제 파일 한도를 800KB로 낮춰 오버헤드 마진 확보. 서버 nginx 설정은 변경하지 않음.

로컬 서버도 2MB 초과 파일은 413을 반환하므로 `fetchFile` 호출 자체를 try-catch로 감싸 스킵.

## remoteFetch 에러 정책

- `409 Conflict` → 무시 (이미 존재 = 멱등성 허용)
- 그 외 4xx / 5xx → throw → 전체 업로드 중단 + toast

401 Unauthorized는 CORS가 아니라 auth 불일치. CORS 실패는 JSON 바디 없이 TypeError로 나타남.

## 설정 저장

원격 서버 URL/auth를 `developerConfigStorage.ts`에 분리 저장 (`sessionviewer.developerConfig`).
기존 `agentConfigStorage`(로컬 서버 auth)와 키 충돌 방지.
