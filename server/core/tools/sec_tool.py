import os
import re
import requests
import pandas as pd

from .base import BaseTool, ToolResult
from ..utils.logger import logger

PATTERN = r"[^a-zA-Z0-9가-힣.,%()|() \t-]+"
DATA_DIR = "/data"
TICKER_PATH = f"{DATA_DIR}/sec_company_tickers.json"
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; MyResearchBot/1.0; contact: myemail@example.com)"
}
SEC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}
os.makedirs(DATA_DIR, exist_ok=True)


def parse_and_clean_markdown_table(text):
    return (
        ""
        if text.isspace() or all(c == "\t" for c in text)
        else re.sub(PATTERN, "", text)
    )


def match_sec_company_tickers(
    df: pd.DataFrame, column: str, query: str
) -> pd.DataFrame:
    p = (
        "[^a-zA-Z0-9]*".join(list(re.escape(query)))
        if column == "title"
        else f"^{re.escape(query)}$"
    )
    return df[df[column].astype(str).str.contains(p, case=False, na=False, regex=True)]


def get_ticker_and_cik(company_name: str) -> tuple[str, str]:
    if os.path.exists(TICKER_PATH):
        df = pd.read_json(TICKER_PATH)
    else:
        res = requests.get(
            "https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS
        )
        res.raise_for_status()
        df = pd.DataFrame(res.json()).T
        df.to_json(TICKER_PATH, orient="records", force_ascii=False)
    df.columns = ["cik_str", "ticker", "title"]
    rows = match_sec_company_tickers(df, "ticker", company_name)
    if rows.empty:
        rows = match_sec_company_tickers(df, "title", company_name)
    if rows.empty:
        raise ValueError(
            f"회사명을 찾을 수 없습니다: {company_name}. 회사명이 정확한지 확인해주세요."
        )
    row = rows.iloc[0]
    return re.sub(r"[^a-zA-Z0-9]", "", row["ticker"].lower()), str(
        row["cik_str"]
    ).zfill(10)


def get_10k_html_link(company_name: str, year=2025) -> str:
    ticker, cik = get_ticker_and_cik(company_name)
    print(f"Ticker: {ticker}, CIK: {cik}")
    res = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=UA)
    res.raise_for_status()
    filings = res.json().get("filings", {}).get("recent", {})
    if not filings:
        raise ValueError(f"No recent filings found for {company_name} ({ticker})")
    forms, dates, accs = (
        filings.get("form", []),
        filings.get("reportDate", []),
        filings.get("accessionNumber", []),
    )
    if len(forms) != len(dates) or len(forms) != len(accs):
        raise ValueError(
            "Mismatch in lengths of 'form', 'reportDate', and 'accessionNumber' fields."
        )
    html_url = ""
    for form, d, a in zip(forms, dates, accs):
        if form == "10-K" and d.startswith(str(year)):
            d = d.replace("-", "")
            acc_no = a.replace("-", "")
            for suffix in ["", "x10k"]:
                html_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/{ticker}-{d}{suffix}.htm"
                r = requests.get(html_url, headers=UA)
                if r.ok:
                    return html_url
    raise ValueError(
        f"❌ 10-K report not found for {company_name} ({ticker}) in {year}. URLs: {html_url}"
    )


def fetch_using_readerLLM(corp: str, url: str):
    res = requests.get(
        f"https://r.jina.ai/{url}",
        params={"X-Engine": "browser", "X-Retain-Images": "none"},
    )
    res.raise_for_status()
    text = [
        t
        for line in res.text.split("\n")
        if (t := parse_and_clean_markdown_table(line))
    ]
    with open(f"{DATA_DIR}/{corp}-10-k.html", "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    return text


def fetch_company_data(corp: str, year=2025) -> str:
    url = get_10k_html_link(corp, year)
    logger.info(f"source url: {url}")
    # TODO: Behavior Change
    return "".join(fetch_using_readerLLM(corp, url))


class SECTool(BaseTool):
    def __init__(self):
        super().__init__("sec_tool", "Fetch SEC 10-K filing content via Jina Reader.")

    async def execute(self, **kwargs) -> ToolResult:
        corp = kwargs.get("corp") or kwargs.get("company_name") or kwargs.get("ticker")
        year = kwargs.get("year", 2025)
        if not corp:
            return ToolResult(success=False, result=None, error="'corp' is required")
        try:
            return ToolResult(
                success=True,
                result={
                    "corp": corp,
                    "year": year,
                    "content": fetch_company_data(corp, year),
                },
            )
        except Exception as e:
            return ToolResult(success=False, result=None, error=str(e))

    def get_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "corp": {
                            "type": "string",
                            "description": "Company ticker or name",
                        },
                        "year": {
                            "type": "integer",
                            "description": "10-K filing year (YYYY)",
                            "default": 2025,
                        },
                    },
                    "required": ["corp"],
                },
            },
        }
