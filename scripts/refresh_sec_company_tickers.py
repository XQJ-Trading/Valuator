#!/usr/bin/env python3
"""Download SEC company_tickers.json and write data/sec_company_tickers.json.

Same source and record shape as domain/company.py and valuator/tools/sec_tool.py.
Run periodically or when a US ticker is missing from the local snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_PATH = ROOT / "data" / "sec_company_tickers.json"
SEC_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Valuator/1.0; contact: research@example.com)",
    "Accept-Encoding": "gzip, deflate",
}


def fetch_records() -> list[dict]:
    import requests

    response = requests.get(SEC_URL, headers=SEC_HEADERS, timeout=120)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return [dict(v) for v in payload.values()]
    if isinstance(payload, list):
        return [dict(r) for r in payload]
    raise ValueError("unexpected SEC company_tickers payload shape")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_PATH,
        help=f"Output JSON path (default: {DATA_PATH})",
    )
    args = parser.parse_args()
    out = Path(args.output).expanduser()
    if not out.is_absolute():
        out = (ROOT / out).resolve()

    records = fetch_records()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(records)} records to {out}")


if __name__ == "__main__":
    main()
