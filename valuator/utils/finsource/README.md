# Finsource Module

Finsource는 금융 데이터를 수집하고 분석하기 위한 유틸리티 모듈입니다. SEC 10-K 보고서와 Yahoo Finance 데이터를 활용하여 기업의 재무 정보를 수집할 수 있습니다.

## 기술적 맥락 이해하기

### 모듈이란?
모듈은 특정 기능을 수행하는 코드의 모음입니다. 마치 금융 분석에서 사용하는 스프레드시트의 시트와 비슷한 개념입니다. 각 시트가 특정 분석을 담당하듯이, 모듈도 특정 기능을 담당합니다.

### 데이터 수집 과정
1. **SEC 10-K 보고서**: 
   - 마치 웹 브라우저에서 보고서를 검색하고 다운로드하는 것과 같습니다.
   - `get_report_url`은 보고서의 주소를 찾고, `fetch_using_readerLLM`은 그 주소에서 보고서를 가져옵니다.

2. **Yahoo Finance 데이터**:
   - 마치 Yahoo Finance 웹사이트에서 재무 데이터를 복사해오는 것과 같습니다.
   - `fetch_income_stmt`와 `fetch_balance_stmt`는 자동으로 이 작업을 수행합니다.

### 데이터 저장
- 수집된 데이터는 컴퓨터의 특정 폴더(`valuator/utils/finsource/data/`)에 저장됩니다.

## 주요 기능

### 1. SEC 10-K 보고서 수집
```python
from valuator.utils.finsource.collector import get_report_url, fetch_using_readerLLM

# 기업의 10-K 보고서 URL 가져오기
corp = "AAPL"  # 애플 주식 심볼
url = get_report_url(corp)  # 마치 SEC 웹사이트에서 보고서 링크를 찾는 것과 같습니다

# 보고서 내용 가져오기
report_content = fetch_using_readerLLM(corp, url)  # 보고서를 자동으로 다운로드하고 읽습니다
```

### 2. 재무제표 데이터 수집
```python
from valuator.utils.finsource.collector import fetch_income_stmt, fetch_balance_stmt

# 손익계산서 데이터 가져오기
income_data = fetch_income_stmt(corp)  # Yahoo Finance에서 손익계산서를 자동으로 가져옵니다
# 반환 데이터:
# {
#     "Total Revenue": [2023, 2022, 2021],  # 마치 엑셀의 행과 열처럼 데이터가 구성됩니다
#     "Operating Income": [2023, 2022, 2021],
#     "Net Income": [2023, 2022, 2021]
# }

# 대차대조표 데이터 가져오기
balance_data = fetch_balance_stmt(corp)  # Yahoo Finance에서 대차대조표를 자동으로 가져옵니다
# 반환 데이터:
# {
#     "Total Assets": [2023, 2022, 2021],
#     "Total Liabilities": [2023, 2022, 2021],
#     "Total Equity": [2023, 2022, 2021]
# }
```

## 사용 예시

### 기업 재무 분석
```python
import pandas as pd  # pandas는 엑셀과 비슷한 데이터 처리 도구입니다
from valuator.utils.finsource.collector import (
    get_report_url,
    fetch_using_readerLLM,
    fetch_income_stmt,
    fetch_balance_stmt
)

def analyze_company(corp: str):
    # 1. 10-K 보고서 수집 (마치 수동으로 보고서를 다운로드하는 것과 같습니다)
    url = get_report_url(corp)
    report_content = fetch_using_readerLLM(corp, url)
    
    # 2. 재무제표 데이터 수집 (마치 Yahoo Finance에서 데이터를 복사해오는 것과 같습니다)
    income_data = fetch_income_stmt(corp)
    balance_data = fetch_balance_stmt(corp)
    
    # 3. 데이터 분석
    # 여기에 분석 로직 추가 (마치 엑셀에서 수식을 작성하는 것과 같습니다)
    
    return {
        "report": report_content,
        "income": income_data,
        "balance": balance_data
    }
```

## 주의사항

1. `get_report_url` 함수는 LLM을 사용하여 SEC 10-K 보고서 URL을 찾습니다.
   - LLM은 마치 지능적인 검색 엔진처럼 작동합니다.
2. `fetch_using_readerLLM` 함수는 수집된 데이터를 `valuator/utils/finsource/data/` 디렉토리에 저장합니다.
   - 마치 파일을 특정 폴더에 저장하는 것과 같습니다.
3. Yahoo Finance 데이터는 최근 3년치 데이터만 제공됩니다.
   - 마치 Yahoo Finance 웹사이트에서 볼 수 있는 데이터 범위와 동일합니다.
4. 모든 금액은 USD 기준입니다.
   - 데이터는 모두 달러로 통일되어 있습니다.

## 의존성

- yfinance: Yahoo Finance 데이터 수집 (마치 Yahoo Finance API를 사용하는 것과 같습니다)
- requests: HTTP 요청 처리 (마치 웹 브라우저가 웹사이트에 접속하는 것과 같습니다)
- valuator.utils.llm_zoo: LLM 기능 사용 (마치 지능적인 검색 엔진을 사용하는 것과 같습니다) 