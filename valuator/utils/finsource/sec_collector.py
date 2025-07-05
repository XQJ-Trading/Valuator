import re
import os
import requests

import pandas as pd


def match_sec_company_tickers(
    df: pd.DataFrame, column: str, query: str
) -> pd.DataFrame:
    escaped_query = re.escape(query)
    if column == "title":
        pattern = "[^a-zA-Z0-9]*".join(list(escaped_query))
    else:
        pattern = f"^{re.escape(query)}$"

    return df[
        df[column].astype(str).str.contains(pattern, case=False, na=False, regex=True)
    ]


def get_ticker_and_cik(company_name: str) -> tuple[str, str]:
    """
    회사명을 입력받아 Ticker-CIK JSON을 로드하여, 해당 회사의 Ticker와 CIK를 반환합니다.

    Ticker-CIK JSON 예시:
    >>> {"cik_str":789019,"ticker":"MSFT","title":"MICROSOFT CORP"}

    Example:
    (ticker, cik) = get_ticker_and_cik("Microsoft")
    >>> msft 0000789019
    """
    company_ticker_path = "valuator/utils/finsource/data/sec_company_tickers.json"
    if os.path.exists(company_ticker_path):
        with open(company_ticker_path, "r", encoding="utf-8") as f:
            df = pd.read_json(f)
    else:
        # SEC에서 Ticker-CIK 매핑 JSON 로드
        url = "https://www.sec.gov/files/company_tickers.json"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()
        df = pd.DataFrame(data).T
        df.to_json(
            company_ticker_path,
            orient="records",
            force_ascii=False,
        )
    df.columns = ["cik_str", "ticker", "title"]

    matched_rows = None

    ticker_matches = match_sec_company_tickers(df, "ticker", company_name)

    if not ticker_matches.empty:
        matched_rows = ticker_matches.iloc[0]
    else:
        title_matches = match_sec_company_tickers(df, "title", company_name)
        if not title_matches.empty:
            matched_rows = title_matches.iloc[0]

    if matched_rows is not None:
        ticker = matched_rows["ticker"].lower()
        cik = str(matched_rows["cik_str"]).zfill(10)
        return re.sub(r"[^a-zA-Z0-9]", "", ticker), cik
    else:
        raise ValueError(
            f"회사명을 찾을 수 없습니다: {company_name}. "
            "회사명이 정확한지 확인해주세요."
        )


def get_10k_html_link(company_name: str, year=2024) -> str:
    """
    회사명과 연도를 입력받아 해당 회사의 10-K 보고서 HTML 링크를 반환합니다.
    """
    ticker, cik = get_ticker_and_cik(company_name)
    print(f"Ticker: {ticker}, CIK: {cik}")

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MyResearchBot/1.0; contact: myemail@example.com)"  # header에 email 주소가 반드시 필요함.
    }
    res = requests.get(url, headers=headers)
    res.raise_for_status()

    data = res.json()

    # filings: 제출 내역에 대한 정보가 담긴 딕셔너리
    # recent: 최근 제출된 서류들의 메타데이터 포함
    filings = data.get("filings", {}).get("recent", {})

    if not filings:
        raise ValueError(f"No recent filings found for {company_name} ({ticker})")

    # filings 내부 주요 필드 (배열 형태)
    # form: 제출된 서류 종류 (예: "10-K", "10-Q", "8-K" 등)
    # reportDate: 각 제출 서류의 보고일자 (YYYY-MM-DD)
    # accessionNumber: 제출 문서 고유 번호 (하이픈 포함)

    # 아래 루프에서 form이 "10-K"이고 연도가 일치하는 서류를 찾음
    # Validate that all required fields have consistent lengths
    forms = filings.get("form", [])
    report_dates = filings.get("reportDate", [])
    accession_numbers = filings.get("accessionNumber", [])
    if not (len(forms) == len(report_dates) == len(accession_numbers)):
        raise ValueError(
            "Mismatch in lengths of 'form', 'reportDate', and 'accessionNumber' fields."
        )

    html_url = ""
    for i, (form, report_date, accession_number) in enumerate(
        zip(forms, report_dates, accession_numbers)
    ):
        if form == "10-K" and report_date.startswith(str(year)):
            # 보고일자에서 하이픈 제거하여 YYYYMMDD 형식으로 변환
            report_date = report_date.replace("-", "")
            # accessionNumber에서 하이픈 제거
            acc_no = accession_number.replace("-", "")

            # SEC EDGAR의 HTML 보고서 URL 구성
            for suffix in ["", "x10k"]:
                try:
                    html_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/{ticker}-{report_date}{suffix}.htm"
                    headers = {
                        "User-Agent": "Mozilla/5.0 (compatible; MyResearchBot/1.0; contact: myemail@example.com)"  # header에 email 주소가 반드시 필요함.
                    }
                    response = requests.get(html_url, headers=headers)
                    response.raise_for_status()
                    return html_url
                except requests.exceptions.RequestException as e:
                    print(f"[DEBUG] Failed to fetch {url}: {e}")
    raise ValueError(
        f"❌ 10-K report not found for {company_name} ({ticker}) in {year}. URLs: {html_url}"
    )
