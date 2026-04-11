# stockelper-kg 온톨로지 ↔ KRX · KIS API 매핑

[stockelper-kg `ontology.py`](https://github.com/Stockelper-Lab/stockelper-kg/blob/main/src/stockelper_kg/graph/ontology.py)의 **Security**, **StockPrice**, **Indicator** 노드를 기준으로, Valuator 코드와 외부 API를 연결한다.

**주의:** KIS의 **TR ID·응답 필드명은 개발자센터가 단일 진실 공급원**이다. 아래 TR ID는 문서·샘플 기준으로 적었고, 배포 전 [KIS Developers](https://apiportal.koreainvestment.com/) 해당 API 상세에서 재확인한다.

---

## Valuator에서 이미 쓰는 것 (KRX “대체” 경로)

| 온톨로지 `Security` / 회사 식별 | Valuator 소스 | 비고 |
|----------------------------------|---------------|------|
| `stock_code` (6자리) | OpenDart `corpCode.xml` → `stock_code` | [`krx_ticker_resolve`](../domain/boundary/krx_ticker_resolve.py) |
| 시장 구분 (`market` 유사) | OpenDart `company.json` → `corp_cls` → `KOSPI` / `KOSDAQ` / `KONEX` | `Listing.exchange` |
| 야후 심볼 (티커 유사) | `vendor_symbols["yahoo"]` = `{code}.KS` 등 | `Listing.yahoo_symbol` — SubjectContext의 “티커” 표시에 활용 가능 |
| 회사명 | `corp_name` | `Company` / seed |

정적 `data/krx_securities.json` 시드가 있으면 동일하게 `ListingSeed`에 합류한다 ([`company.py`](../domain/company.py)).

**ISIN**은 온톨로지 `Security.isin`에 해당하지만, Valuator 경로만으로는 채워지지 않는다. 아래 **KRX/공공데이터** 또는 **KIS 종목정보**로 보강한다.

---

## 1. `Security` (종목 메타)

| 온톨로지 `key` | 권장 출처 | API / 식별 |
|----------------|-----------|------------|
| `stock_code` | 이미 보유 + KIS/KRX 조회 키로 동일 6자리 사용 | `FID_INPUT_ISCD` / 단축코드 |
| `isin` | [금융위원회 KRX상장종목정보](https://www.data.go.kr/) (공공데이터포털) 등 — 단축코드·ISIN 매핑 | 또는 KIS **[국내주식] 종목정보** 계열 API (포털에서 “종목기본정보” 검색) |
| `market` | OpenDart `corp_cls` 또는 KRX 시장구분 필드 | Valuator는 이미 `Listing.exchange` |
| `currency` | 국내 상장 보통 `KRW` 고정 가능 | 필요 시 KRX/KIS 메타에 명시된 통화 |
| `ticker` | 해외 거래소 표기; 국내는 `stock_code` + 거래소 접미사 정책 | `005930.KS` 등은 `Listing.yahoo_symbol`과 동일 개념 |

KIS **기본시세**는 종목코드만 있으면 되므로, `Security`는 **Valuator `Listing` + (선택) ISIN 조회**로 충분한 경우가 많다.

---

## 2. `StockPrice` — KIS 국내주식 일·시세

온톨로지 주석: **KIS inquire-daily-price**, 필드 `stck_oprc`, `stck_prpr`, `stck_hgpr`, `stck_lwpr`, `stck_mxpr`, `stck_llam`, `stck_sdpr`.

### 2a. 일자별 시세 (과거 OHLC 등)

| 항목 | 값 (확인용) |
|------|-------------|
| **카테고리** | [국내주식] 기본시세 |
| **API명 (예시)** | 주식현재가 일자별 / `inquire-daily-price` |
| **REST path (예시)** | `/uapi/domestic-stock/v1/quotations/inquire-daily-price` |
| **TR ID (실전·모의 각각)** | 개발자센터 표기 따름 (예: 일부 문서에서 `FHKST01010400` — **반드시 포털에서 재확인**) |
| **공통 query** | `FID_COND_MRKT_DIV_CODE`=`J`(주식), `FID_INPUT_ISCD`=종목코드, 기간·수정주가 등 |

**응답 `output[]` 매핑 (일반적 필드명 — 포털 스펙 우선):**

| 온톨로지 `StockPrice` | KIS 출력 필드 (관례) |
|-----------------------|----------------------|
| 시가 `stck_oprc` | `stck_oprc` |
| 종가 `stck_prpr` | `stck_prpr` 또는 일자별 종가 필드명 |
| 고가 `stck_hgpr` | `stck_hgpr` |
| 저가 `stck_lwpr` | `stck_lwpr` |
| 상한가 `stck_mxpr` | `stck_mxpr` |
| 하한가 `stck_llam` | `stck_llam` |
| 전일종가 `stck_sdpr` | `stck_sdpr` |

Primary key `("stock_code", "traded_at")` → 응답의 **일자 필드**(예: `stck_bsop_date`)와 조합.

### 2b. 현재가 스냅샷 (스냅샷 1회용)

SubjectContext처럼 **당일 시세·상하한**만 필요하면 **주식현재가 시세**가 맞다.

| 항목 | 값 (확인용) |
|------|-------------|
| **API명** | 주식현재가 시세 / `inquire-price` |
| **REST path (예시)** | `/uapi/domestic-stock/v1/quotations/inquire-price` |
| **TR ID** | 문서·샘플에서 `FHKST01010100`로 안내되는 경우가 많음 — **포털 확인** |
| **query** | `FID_COND_MRKT_DIV_CODE`=`J`, `FID_INPUT_ISCD`=종목코드 |

출력에 현재가, 전일대비, **상한가/하한가**, 시고저 등이 포함되는지 스펙에서 필드명을 그대로 쓰면 온톨로지 `StockPrice`와 정합이 쉽다.

---

## 3. `Indicator` — KIS PER · EPS · PBR · BPS

온톨로지: **KIS inquire-price**, `eps`, `per`, `pbr`, `bps`. Primary `("stock_code", "as_of")`.

실무적으로는 **같은 `inquire-price` 응답**에 PER, EPS, PBR, BPS, 시가총액 등이 포함되는 경우가 많다. 필드명은 **해당 API 최신 스펙**의 예시 JSON을 기준으로 매핑한다 (예: `per`, `pbr`, `eps`, `bps` 또는 `stck_*` 접두).

**forward PER**는 온톨로지 `Indicator` 단일 스키마에 없고, SubjectContext 설계에는 `forward_pe`가 별도 필드로 있다 ([`subject-context-plan.md`](./subject-context-plan.md)). KIS 단일 호출에 없으면 다른 출처 또는 생략.

---

## 4. KRX 전용 REST / 공공데이터 (ISIN · 시장 메타)

| 목적 | 출처 |
|------|------|
| 상장 목록·ISIN·시장구분 | 금융위원회 **KRX상장종목정보** Open API ([data.go.kr](https://www.data.go.kr/) 검색) |
| KRX 정보데이터시스템 OPEN API | [KRX Data Marketplace](https://openapi.krx.co.kr/) — 서비스별 인증·쿼터 |

Valuator는 당장 **OpenDart + Listing**으로 `stock_code`·시장·야후 심볼을 갖추므로, **ISIN·정식 시장 라벨**이 필요할 때만 KRX/공공 API를 추가하면 된다.

---

## 5. 구현 순서 제안 (SubjectContext / KG 정합)

1. **키**: `Listing.security_code` + `Listing.yahoo_symbol` (이미 경계에서 확정).
2. **시세·지표**: KIS `inquire-price` 1회로 `Indicator` + 당일 가격 요약; 필요 시 `inquire-daily-price`로 `StockPrice` 시계열.
3. **ISIN**: 선택 — 공공데이터 KRX상장종목정보 또는 KIS 종목기본정보로 `Security.isin` 채움.

---

## 6. 참고 링크

- [KIS Developers — 국내주식 기본시세](https://apiportal.koreainvestment.com/) (API 목록에서 `inquire-price`, `inquire-daily-price` 검색)
- [한국투자 GitHub 샘플](https://github.com/koreainvestment/open-trading-api) (TR ID·예제 코드)
- [공공데이터포털 — 금융위원회 KRX상장종목정보](https://www.data.go.kr/)
