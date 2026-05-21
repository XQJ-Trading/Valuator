#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from valuator.tools.sec_tool import fetch_reader_lines, get_10k_html_link  # noqa: E402

DEFAULT_OUTPUT_DIR = ROOT / "data" / "page_index"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a SEC 10-K reader text file for PageIndex input."
    )
    parser.add_argument("--ticker", required=True, help="SEC ticker, e.g. AAPL")
    parser.add_argument("--year", type=int, required=True, help="10-K report year")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR.relative_to(ROOT)}",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Optional explicit output text path.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (ROOT / expanded).resolve()


def safe_ticker(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).lower()
    if not normalized:
        raise ValueError("ticker must contain at least one alphanumeric character")
    return normalized


def default_output_path(
    *,
    output_dir: Path,
    ticker: str,
    year: int,
) -> Path:
    return output_dir / f"{safe_ticker(ticker)}-{year}.txt"


def main() -> None:
    args = parse_args()
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filing_url, used_year = get_10k_html_link(args.ticker, args.year)
    lines = fetch_reader_lines(args.ticker, filing_url)

    output_path = (
        resolve_path(args.output_file)
        if args.output_file is not None
        else default_output_path(
            output_dir=output_dir,
            ticker=args.ticker,
            year=used_year,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    metadata = {
        "ticker": safe_ticker(args.ticker).upper(),
        "requested_year": args.year,
        "used_year": used_year,
        "filing_url": filing_url,
        "line_count": len(lines),
        "output_file": str(output_path),
    }
    metadata_path = output_path.with_suffix(".metadata.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({**metadata, "metadata_file": str(metadata_path)}, indent=2))


if __name__ == "__main__":
    main()
