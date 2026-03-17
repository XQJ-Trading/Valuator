from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT_DIR / "data" / "krx_securities.json"
KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
MARKET_TYPES = {
    "KOSPI": "stockMkt",
    "KOSDAQ": "kosdaqMkt",
    "KONEX": "konexMkt",
}
ENGLISH_NAME_COLUMNS = (
    "영문명",
    "영문 회사명",
    "회사명(영문)",
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Referer": KIND_URL})

    records: list[dict[str, object]] = []
    for exchange, market_type in MARKET_TYPES.items():
        records.extend(_download_market(session, exchange=exchange, market_type=market_type))

    records.sort(key=lambda record: str(record["security_code"]))
    OUTPUT_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(records)} securities to {OUTPUT_PATH}")


def _download_market(
    session: requests.Session,
    *,
    exchange: str,
    market_type: str,
) -> list[dict[str, object]]:
    response = session.get(
        KIND_URL,
        params={
            "method": "download",
            "searchType": "13",
            "marketType": market_type,
        },
        timeout=30,
    )
    response.raise_for_status()

    rows = _parse_html_table(response.text)
    if not rows:
        raise RuntimeError(f"no KRX table returned for {exchange}")
    headers = rows[0]
    body = rows[1:]

    records: list[dict[str, object]] = []
    for values in body:
        row = _row_map(headers, values)
        issuer_name = _value(row, "회사명")
        security_code = _value(row, "종목코드").zfill(6)
        english_name = _value(row, *ENGLISH_NAME_COLUMNS)
        if not issuer_name or not security_code:
            continue
        aliases = [issuer_name]
        if english_name:
            aliases.append(english_name)
        records.append(
            {
                "issuer_name": issuer_name,
                "security_code": security_code,
                "exchange": exchange,
                "listing_id": f"KRX:{security_code}",
                "vendor_symbols": _vendor_symbols(exchange, security_code),
                "aliases": list(dict.fromkeys(aliases)),
            }
        )
    return records


def _value(row: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _row_map(headers: list[str], values: list[str]) -> dict[str, str]:
    padded = list(values) + [""] * max(0, len(headers) - len(values))
    return {
        header: padded[index].strip()
        for index, header in enumerate(headers)
    }


def _parse_html_table(html: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.rows


def _vendor_symbols(exchange: str, security_code: str) -> dict[str, str]:
    if exchange == "KOSDAQ":
        return {"yahoo": f"{security_code}.KQ"}
    if exchange == "KOSPI":
        return {"yahoo": f"{security_code}.KS"}
    return {"yahoo": security_code}


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_table = False
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
            if not self._in_table:
                self._in_table = True
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._in_row = True
            self._row = []
            return
        if tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._in_table = False
            return
        if not self._in_table:
            return
        if tag in {"td", "th"} and self._in_cell:
            self._in_cell = False
            self._row.append("".join(self._cell_parts).strip())
            self._cell_parts = []
            return
        if tag == "tr" and self._in_row:
            self._in_row = False
            if self._row:
                self.rows.append(self._row)
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_table and self._in_cell:
            self._cell_parts.append(data)


if __name__ == "__main__":
    main()
