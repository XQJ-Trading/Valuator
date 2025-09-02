"""
Common utilities for financial analysis modules.
"""

import logging
from io import StringIO
from typing import Union

import pandas as pd

from valuator.utils.llm_utils import retry
from valuator.utils.basic_utils import parse_json_from_llm_output
from valuator.utils.llm_zoo import gpt_41_nano, gpt_41_mini
from valuator.utils.finsource.collector import fetch_using_readerLLM
from valuator.utils.finsource.sec_collector import get_10k_html_link
from valuator.utils.prompt_manager import get_prompt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)
logger = logging.getLogger(__name__)


def setup_logging():
    """Configure logging for all modules in waterfall_architecture."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    )
    return logging.getLogger(__name__)


def format_currency_millions(value: Union[int, float, str]) -> float:
    """
    Convert currency value to millions of USD.

    Args:
        value: Currency value (can be in various formats)

    Returns:
        Value in millions of USD
    """
    if isinstance(value, str):
        # Remove currency symbols and commas
        value = value.replace("$", "").replace(",", "").replace("%", "")
        try:
            value = float(value)
        except ValueError:
            return 0.0

    # Convert to millions if the value is likely in thousands or units
    if value > 1_000_000_000:  # Likely in units
        return value / 1_000_000
    elif value > 1_000_000:  # Likely in thousands
        return value / 1_000
    else:
        return value


def create_llm_prompt_template(template_type: str, **kwargs) -> str:
    """Load LLM prompt templates from YAML via prompt manager."""
    return get_prompt("analysis", template_type, **kwargs)


def format_markdown_table(headers: list, rows: list, title: str = "") -> str:
    """
    Create a formatted markdown table.

    Args:
        headers: List of column headers
        rows: List of row data
        title: Optional table title

    Returns:
        Formatted markdown table string
    """
    if not headers or not rows:
        return ""

    table_parts = []
    if title:
        table_parts.append(f"## {title}\n")

    # Header row
    table_parts.append("| " + " | ".join(headers) + " |")

    # Separator row
    table_parts.append("|" + "|".join(["------" for _ in headers]) + "|")

    # Data rows
    for row in rows:
        table_parts.append("| " + " | ".join(str(cell) for cell in row) + " |")

    return "\n".join(table_parts)


def fetch_company_data(corp: str) -> str:
    """
    Fetch company financial data from SEC filings.

    Args:
        corp: Company ticker or name
        year: Year for the filing

    Returns:
        Concatenated financial data as string
    """
    url = get_10k_html_link(corp)
    logger.info(f"source url: {url}")
    source = fetch_using_readerLLM(corp, url)

    summary = ""
    chunk_size = 2000
    for s in range(0, len(source), chunk_size):
        e = min(s + chunk_size, len(source))
        logger.info(f"step: {s} / {len(source)}")
        src = "".join(source[s:e])
        chunk_summary = gpt_41_nano.invoke(
            create_llm_prompt_template("company_summary", source_chunk=src)
        ).content
        summary += str(chunk_summary)

    return summary


@retry(tries=3)
def extract_segments_in_company(
    corp: str, summary: str, year: int = 2024
) -> pd.DataFrame:
    """
    Extract segment-wise revenue and operating income data.

    Args:
        corp: Company name
        summary: Financial summary text
        year: Year for analysis

    Returns:
        JSON string with segment data
    """
    segments = gpt_41_mini.invoke(
        get_prompt(
            "analysis",
            "segment_jsonl_extraction",
            corp=corp,
            summary=summary,
            year=year,
        )
    ).content

    logger.info(f"Segments JSON: {segments}")
    segments = pd.read_json(StringIO(str(segments)), lines=True)
    return segments


def extract_balance_sheet(summary: str) -> str:
    """
    Extract balance sheet information from financial summary.

    Args:
        summary: Financial summary text

    Returns:
        JSON string with balance sheet data
    """
    balance_sheet_json_str = gpt_41_mini.invoke(
        get_prompt("analysis", "balance_sheet_extraction", summary=summary)
    ).content

    return str(balance_sheet_json_str)


def format_balance_sheet_markdown(balance_sheet_json_str: str) -> str:
    """
    Format balance sheet JSON data as markdown table.

    Args:
        balance_sheet_json_str: JSON string with balance sheet data

    Returns:
        Formatted markdown string
    """
    balance_sheet_table_md = (
        "## Detailed Balance Sheet\n\nNot available or could not be parsed.\n"
    )
    try:
        # Strip Markdown code fences if present
        bs_data = parse_json_from_llm_output(balance_sheet_json_str).get(
            "balance_sheet", {}
        )

        if bs_data:
            md_parts = ["## Detailed Balance Sheet\n"]

            for category, details in [
                ("Assets", bs_data.get("assets")),
                ("Liabilities", bs_data.get("liabilities")),
                ("Equity", bs_data.get("equity")),
            ]:
                if not details:
                    continue

                md_parts.append(f"### {category}\n")
                md_parts.append("| Item                      | Amount   |")
                md_parts.append("|---------------------------|----------|")
                md_parts.append(
                    f"| **Total {category}**      | **{details.get('total', 'N/A')}** |"
                )
                for comp in details.get("components", []):
                    md_parts.append(
                        f"| {comp.get('item', 'N/A')}         | {comp.get('value', 'N/A')}    |"
                    )
                md_parts.append("\n")

            balance_sheet_table_md = "\n".join(md_parts)
        else:
            logger.warning("Balance sheet data was empty after parsing.")

    except Exception as e:
        logger.warning(
            f"An unexpected error occurred while processing balance sheet data: {e}"
        )
        logger.warning(f"Raw Balance Sheet LLM output: {balance_sheet_json_str}")

    return balance_sheet_table_md
