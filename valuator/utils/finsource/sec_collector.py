import os
import requests

import pandas as pd


def get_ticker_and_cik(company_name):
    company_ticker_path = "./utils/finsource/data/sec_company_tickers.json"
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

    # 회사명 검색 (대소문자 무시)
    matched = df[df["title"].str.contains(company_name, case=False, na=False)]

    if not matched.empty:
        ticker = matched.iloc[0]["ticker"].lower()
        cik = str(matched.iloc[0]["cik_str"]).zfill(10)  # 10자리 0-padding
        return ticker, cik
    else:
        ValueError(
            f"회사명을 찾을 수 없습니다: {company_name}. "
            "회사명이 정확한지 확인해주세요."
        )


def get_10k_html_link(corp, year=2024):
    ticker, cik = get_ticker_and_cik(corp)
    print(f"Ticker: {ticker}, CIK: {cik}")

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MyResearchBot/1.0; contact: myemail@example.com)"
    }
    res = requests.get(url, headers=headers)
    res.raise_for_status()

    data = res.json()
    filings = data.get("filings", {}).get("recent", {})
    if not filings:
        raise ValueError(f"No recent filings found for {corp} ({ticker})")

    for i, form in enumerate(filings.get("form", [])):
        if form == "10-K" and filings["reportDate"][i].startswith(str(year)):
            # if form == "10-K":
            report_date = filings["reportDate"][i].replace("-", "")
            acc_no = filings["accessionNumber"][i].replace("-", "")
            html_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/{ticker}-{report_date}.htm"
            return html_url
