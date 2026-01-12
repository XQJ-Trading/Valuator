import asyncio
import os
import re

import requests
import pandas as pd

from .base import BaseTool, ToolResult
from ..models.gemini_direct import GeminiModel
from ..utils.config import config
from ..utils.logger import logger

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
TICKER_PATH = f"{DATA_DIR}/sec_company_tickers.json"

SEC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MyResearchBot/1.0; contact: myemail@example.com)",
    "Accept-Encoding": "gzip, deflate",
}
CHUNK_SIZE = 2000
CHUNK_SYSTEM_PROMPT = (
    "You extract only SEC 10-K details that answer the inquiry. "
    "Stay within the provided chunk and keep outputs terse."
)
CHUNK_PROMPT = (
    "10-K slice:\n"
    "{chunk}\n\n"
    "Retrieve the information from the above 10-K chunk that is needed to answer the query: {query}."
)
FINAL_SYSTEM_PROMPT = (
    "You combine extracted SEC findings into a direct answer. "
    "Use only the supplied notes and keep the response concise."
)
FINAL_PROMPT = (
    'Based on the extracted notes: {notes}, analyze and answer the query "{query}" from multiple perspectives. '
    "Use only the provided information, and keep your response clear and concise."
)


def load_ticker_table() -> pd.DataFrame:
    if os.path.exists(TICKER_PATH):
        return pd.read_json(TICKER_PATH)
    res = requests.get(
        "https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS
    )
    res.raise_for_status()
    df = pd.DataFrame(res.json()).T
    df.to_json(TICKER_PATH, orient="records", force_ascii=False)
    return df


def parse_and_clean_markdown_table(
    text: str, pattern: str = r"[^a-zA-Z0-9가-힣.,%()| \t-]+"
) -> str:
    if not text or text.isspace():
        return ""
    return re.sub(pattern, "", text)


def get_ticker_and_cik(ticker: str) -> tuple[str, str]:
    df = load_ticker_table()
    df.columns = ["cik_str", "ticker", "title"]
    ticker = re.sub(r"[^a-zA-Z0-9]", "", ticker).lower()
    rows = df[df["ticker"].astype(str).str.lower() == ticker]
    if rows.empty:
        raise ValueError(
            f"티커를 찾을 수 없습니다: {ticker}. 티커가 정확한지 확인해주세요."
        )
    row = rows.iloc[0]
    return ticker, str(row["cik_str"]).zfill(10)


def get_10k_html_link(ticker: str, year: int = 2024) -> str:
    ticker, cik = get_ticker_and_cik(ticker)
    logger.info(f"ticker={ticker}, cik={cik}")
    res = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS
    )
    res.raise_for_status()
    filings = res.json().get("filings", {}).get("recent", {})
    if not filings:
        raise ValueError(f"No recent filings found for ticker {ticker}")
    forms, dates, accs = (
        filings.get("form", []),
        filings.get("reportDate", []),
        filings.get("accessionNumber", []),
    )
    if len(forms) != len(dates) or len(forms) != len(accs):
        raise ValueError(
            "Mismatch in lengths of 'form', 'reportDate', and 'accessionNumber' fields."
        )
    target_year = str(year)
    for form, report_date, accession_number in zip(forms, dates, accs):
        if form != "10-K" or not report_date.startswith(target_year):
            continue
        report_date = report_date.replace("-", "")
        acc_no = accession_number.replace("-", "")
        for suffix in ("", "x10k"):
            html_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/{ticker}-{report_date}{suffix}.htm"
            r = requests.get(html_url, headers=SEC_HEADERS)
            if r.ok:
                return html_url
    raise ValueError(f"❌ 10-K report not found for ticker {ticker} in {year}.")


def fetch_using_readerLLM(ticker: str, url: str) -> list[str]:
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
    with open(f"{DATA_DIR}/{ticker}-10-k.html", "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    return text


def fetch_company_data(ticker: str, year: int = 2024) -> list[str]:
    url = get_10k_html_link(ticker, year)
    logger.info(f"source url: {url}")
    return fetch_using_readerLLM(ticker, url)


class SECTool(BaseTool):
    def __init__(self):
        super().__init__(
            "sec_tool",
            (
                "Authoritative SEC 10-K retriever (default year 2024). Resolves ticker/CIK and extracts only the filing details relevant to the provided query instead of returning the raw document. "
                "Output includes a concise answer plus chunk-level findings gathered from 2,000-line SEC slices."
            ),
        )
        self.model = GeminiModel(config.agent_model)

    async def _ask_model(self, system_prompt: str, prompt: str) -> str:
        messages = self.model.format_messages(system_prompt, [], "")
        session = self.model.start_chat_session(messages)
        response = await session.send_message(prompt)
        content = response.content.strip() if response and response.content else ""
        if not content:
            raise ValueError("Empty response from Gemini during SEC extraction.")
        return content

    async def _extract_chunks(self, query: str, lines: list[str]) -> list[str]:
        tasks = [
            self._ask_model(
                CHUNK_SYSTEM_PROMPT,
                CHUNK_PROMPT.format(
                    query=query,
                    chunk="\n".join(lines[start : start + CHUNK_SIZE]),
                ),
            )
            for start in range(0, len(lines), CHUNK_SIZE)
        ]
        results = await asyncio.gather(*tasks)
        return [
            cleaned
            for text in results
            if (cleaned := text.strip())
            and not cleaned.lower().startswith("no relevant")
        ]

    async def _synthesize_findings(self, query: str, findings: list[str]) -> str:
        if not findings:
            return "No relevant SEC data found for this inquiry."
        notes = "\n\n".join(findings)
        prompt = FINAL_PROMPT.format(query=query, notes=notes)
        final = await self._ask_model(FINAL_SYSTEM_PROMPT, prompt)
        return final.strip()

    async def execute(self, **kwargs) -> ToolResult:
        ticker = kwargs.get("ticker") or kwargs.get("corp")
        year = kwargs.get("year", 2024)
        query = kwargs.get("query")
        if not ticker:
            return ToolResult(success=False, result=None, error="'ticker' is required")
        if not query:
            return ToolResult(success=False, result=None, error="'query' is required")
        try:
            lines = fetch_company_data(ticker, year)
            findings = await self._extract_chunks(query, lines)
            summary = await self._synthesize_findings(query, findings)
            return ToolResult(
                success=True,
                result={
                    "ticker": ticker,
                    "year": year,
                    "query": query,
                    "summary": summary,
                    "extracts": findings,
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
                        "query": {
                            "type": "string",
                            "description": "Focused question or objective for SEC extraction; keep it concise",
                        },
                        "ticker": {
                            "type": "string",
                            "description": "Company ticker symbol (e.g., TSLA, AAPL)",
                        },
                        "year": {
                            "type": "integer",
                            "description": "10-K filing year (YYYY)",
                            "default": 2024,
                        },
                    },
                    "required": ["ticker", "query"],
                },
            },
        }
