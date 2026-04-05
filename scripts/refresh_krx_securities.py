from __future__ import annotations

import json
from pathlib import Path

from domain.boundary.krx_ticker_resolve import build_record_from_api, fetch_records
from valuator.utils.config import get_opendart_api_key

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT_DIR / "data" / "krx_securities.json"


def main() -> None:
    api_key = get_opendart_api_key(required=True)
    records = fetch_records(force_remote=True)
    payload: list[dict[str, object]] = []

    for record in records:
        stock_code = str(record.get("stock_code") or "").strip().upper()
        corp_name = str(record.get("corp_name") or "").strip()
        if not stock_code or not corp_name:
            continue

        payload.append(build_record_from_api(record, api_key=api_key))

    payload.sort(key=lambda item: str(item["security_code"]))
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(payload)} KRX listings to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
