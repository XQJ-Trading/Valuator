import re
import requests

import yfinance as yf
from valuator.utils.llm_zoo import pplx


def parse_and_clean_markdown_table(text):
    if text.isspace() or all(c == "\t" for c in text):
        return ""
    else:
        pattern = r"[^a-zA-Z0-9가-힣.,%()|() \t-]+"
        return re.sub(pattern, "", text)


def get_report_url(corp: str) -> str:
    url = pplx.invoke(
        f"""Give me a {corp}'s 2024 10-K(annual report) SEC HTML link.
Link must start with https://www.sec.gov/Archives/edgar/data/
Do not explaination."""
    ).content
    return url


def fetch_using_readerLLM(corp: str, url: str):
    proxy_url = f"https://r.jina.ai/{url}"
    params = {
        "X-Engine": "browser",
        "X-Retain-Images": "none",
    }
    response = requests.get(
        proxy_url,
        params=params,
    )

    response.raise_for_status()
    response = response.text.split("\n")
    text = [
        clean_line
        for line in response
        if (clean_line := parse_and_clean_markdown_table(line))
    ]
    with open(f"valuator/utils/finsource/data/{corp}-10-k.html", "w", encoding="utf-8") as file:
        file.write("\n".join(text))
    return text


def fetch_income_stmt(corp: str):
    stock = yf.Ticker(corp)
    income_stmt = stock.financials

    # 최근 3개년 데이터 추출
    years = income_stmt.columns[:3]

    return {
        "Total Revenue": income_stmt.loc["Total Revenue", years],
        "Operating Income": income_stmt.loc["Operating Income", years],
        "Net Income": income_stmt.loc["Net Income", years],
    }


def fetch_balance_stmt(corp: str):
    stock = yf.Ticker(corp)
    balance_sheet = stock.balance_sheet

    # 최근 3개년 데이터 추출
    years = balance_sheet.columns[:3]

    return {
        "Total Assets": balance_sheet.loc["Total Assets", years],
        "Total Liabilities": balance_sheet.loc[
            "Total Liabilities Net Minority Interest", years
        ],
        "Total Equity": balance_sheet.loc["Stockholders Equity", years],
    }


if __name__ == "__main__":
    # url = "https://www.sec.gov/Archives/edgar/data/1018724/000101872425000004/amzn-20241231.htm"
    url = "https://microsoft.gcs-web.com/node/33446/html"
    html = fetch_using_readerLLM(url)
    print(html[:1000]) 