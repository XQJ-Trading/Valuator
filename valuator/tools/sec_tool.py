from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

import pandas as pd
import requests

from ..models.gemini_direct import GeminiClient
from ..utils.config import config
from ..utils.logger import logger
from .base import BaseTool, ToolResult

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TICKER_PATH = DATA_DIR / "sec_company_tickers.json"

SEC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Valuator/1.0; contact: research@example.com)",
    "Accept-Encoding": "gzip, deflate",
}

CHUNK_SIZE = 2000
CHUNK_SYSTEM_PROMPT = (
    "Extract only filing details relevant to the user query. "
    "Stay strictly inside provided text. If nothing relevant exists, reply 'no relevant'."
)
CHUNK_PROMPT = (
    "10-K text slice:\n"
    "{chunk}\n\n"
    "Retrieve information needed to answer this query:\n"
    "{query}\n"
)


def load_ticker_table() -> pd.DataFrame:
    if TICKER_PATH.exists():
        return pd.read_json(TICKER_PATH)
    response = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=SEC_HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    df = pd.DataFrame(response.json()).T
    df.to_json(str(TICKER_PATH), orient="records", force_ascii=False)
    return df


def get_ticker_and_cik(ticker: str) -> tuple[str, str]:
    df = load_ticker_table()
    df.columns = ["cik_str", "ticker", "title"]
    normalized = re.sub(r"[^a-zA-Z0-9]", "", ticker).lower()
    rows = df[df["ticker"].astype(str).str.lower() == normalized]
    if rows.empty:
        raise ValueError(f"ticker not found: {ticker}")
    row = rows.iloc[0]
    return normalized, str(row["cik_str"]).zfill(10)


def get_10k_html_link(ticker: str, year: int) -> tuple[str, int]:
    ticker, cik = get_ticker_and_cik(ticker)
    logger.info("sec ticker=%s cik=%s", ticker, cik)

    response = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers=SEC_HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    filings = response.json().get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("reportDate", [])
    accs = filings.get("accessionNumber", [])
    if not forms or len(forms) != len(dates) or len(forms) != len(accs):
        raise ValueError("invalid SEC recent filings payload")

    tenk_candidates = sorted(
        (
            (report_date, accession_number)
            for form, report_date, accession_number in zip(forms, dates, accs)
            if form == "10-K" and report_date
        ),
        reverse=True,
    )
    if not tenk_candidates:
        raise ValueError("no 10-K filings found")

    target_year = str(year)
    picks = [candidate for candidate in tenk_candidates if candidate[0].startswith(target_year)]
    if not picks:
        year = int(tenk_candidates[0][0][:4])
        picks = [candidate for candidate in tenk_candidates if candidate[0].startswith(str(year))]

    for report_date, accession_number in picks:
        report_date = report_date.replace("-", "")
        acc_no = accession_number.replace("-", "")
        for suffix in ("", "x10k"):
            html_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/"
                f"{ticker}-{report_date}{suffix}.htm"
            )
            probe = requests.get(html_url, headers=SEC_HEADERS, timeout=20)
            if probe.ok:
                return html_url, year
    raise ValueError(f"10-K report not found for ticker {ticker} in {year}")


def fetch_reader_lines(ticker: str, filing_url: str) -> list[str]:
    safe_ticker = re.sub(r"[^a-zA-Z0-9]", "", ticker).lower()
    url_key = hashlib.sha256(filing_url.encode("utf-8")).hexdigest()[:12]
    cache_path = DATA_DIR / f"{safe_ticker}-{url_key}-10-k-lines.txt"
    if cache_path.exists():
        cached = [line for line in cache_path.read_text(encoding="utf-8").splitlines() if line]
        if cached:
            return cached

    response = requests.get(
        f"https://r.jina.ai/{filing_url}",
        params={"X-Engine": "browser", "X-Retain-Images": "none"},
        timeout=60,
    )
    response.raise_for_status()
    lines = []
    for line in response.text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    cache_path.write_text("\n".join(lines), encoding="utf-8")
    return lines


class SECTool(BaseTool):
    def __init__(self):
        super().__init__(
            "sec_tool",
            "Retrieve relevant 10-K details from SEC EDGAR for a ticker/year/query.",
        )
        self.client = GeminiClient(config.agent_model)

    async def _ask_model(self, system_prompt: str, prompt: str) -> str:
        content = await self.client.generate(prompt=prompt, system_prompt=system_prompt)
        text = content.strip()
        if not text:
            raise ValueError("empty response from Gemini during SEC extraction")
        return text

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

    async def execute(self, **kwargs) -> ToolResult:
        ticker = kwargs.get("ticker") or kwargs.get("corp")
        year = kwargs.get("year")
        query = kwargs.get("query")
        if not ticker:
            return ToolResult(success=False, result=None, error="'ticker' is required")
        if not year:
            return ToolResult(success=False, result=None, error="'year' is required")
        if not query:
            return ToolResult(success=False, result=None, error="'query' is required")

        try:
            year_int = int(year)
            filing_url, used_year = get_10k_html_link(str(ticker), year_int)
            lines = fetch_reader_lines(str(ticker), filing_url)
            findings = await self._extract_chunks(str(query), lines)
            return ToolResult(
                success=True,
                result={
                    "ticker": str(ticker).upper(),
                    "year": used_year,
                    "query": str(query),
                    "filing_url": filing_url,
                    "extracts": findings,
                },
                metadata={
                    "source": "sec_edgar",
                    "line_count": len(lines),
                    "selected_count": len(findings),
                },
            )
        except Exception as exc:
            return ToolResult(success=False, result=None, error=str(exc))

    def get_schema(self) -> dict[str, object]:
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
                            "description": "Focused retrieval query for 10-K content",
                        },
                        "ticker": {
                            "type": "string",
                            "description": "Ticker symbol (e.g., AMZN, TSLA)",
                        },
                        "year": {
                            "type": "integer",
                            "description": "Target filing year",
                        },
                    },
                    "required": ["ticker", "query", "year"],
                },
            },
        }
