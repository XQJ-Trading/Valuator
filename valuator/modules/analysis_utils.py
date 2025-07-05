"""
Common utilities for financial analysis modules.
"""

from valuator.utils.basic_utils import parse_json_from_llm_output
from valuator.utils.llm_zoo import gpt_41_nano, gpt_41_mini
from valuator.utils.finsource.collector import fetch_using_readerLLM
from valuator.utils.finsource.sec_collector import get_10k_html_link


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
    print(f"source url: {url}")
    source = fetch_using_readerLLM(corp, url)

    summary = ""
    chunk_size = 2000
    for s in range(0, len(source), chunk_size):
        e = min(s + chunk_size, len(source))
        print(f"step: {s} / {len(source)}")
        src = "".join(source[s:e])
        chunk_summary = gpt_41_nano.invoke(
            f"""## Role
You are acting as an expert financial analyst specializing in segment performance analysis. Your task is to break down revenue and profitability metrics across different business segments from financial statements.

## Main Task
- You analyze annual financial statements from the provided source material.
- The analysis should cover both company-wide performance and segment-specific metrics.
- When data appears inconsistent or incomplete, note this in your analysis.

## Specific Tasks
1. **Company-wide Financial Overview**:
    - Extract key metrics from the income statement: total revenue, operating income, and operating margin (%)
    - From the balance sheet, collect:
        * Total Assets
        * Key Asset Components (extract up to 5 most significant, e.g., Cash & Cash Equivalents, Accounts Receivable, Inventories, PP&E, Goodwill)
        * Total Liabilities
        * Key Liability Components (extract up to 5 most significant, e.g., Accounts Payable, Accrued Expenses, Short-Term Debt, Long-Term Debt, Deferred Revenue)
        * Total Stockholders' Equity
        * Key Equity Components (extract up to 3-4 most significant, e.g., Common Stock, Retained Earnings, Accumulated Other Comprehensive Income)

2. **Segment Analysis**:
    - Identify all business segments mentioned in the source material
    - For each segment, extract:
    * Revenue
    * Operating income
    * Operating margin (%)
    * Percentage of total company revenue
    * Year-over-year growth rates (if data is available)

## Output Requirements
- Begin with a brief executive summary highlighting key findings (1-2 paragraphs)
- Present the company-wide financial overview table
- Present segment performance tables with comparative metrics
- Organize all data into clearly formatted markdown tables

## Source Material
Please analyze the following financial data:
{src}
"""
        ).content
        summary += str(chunk_summary)

    return summary


def extract_segments_in_company(corp: str, summary: str, year: int = 2024) -> str:
    """
    Extract segment-wise revenue and operating income data.

    Args:
        corp: Company name
        summary: Financial summary text
        year: Year for analysis

    Returns:
        JSON string with segment data
    """
    segments_json = gpt_41_mini.invoke(
        f"""[Goal]
- You are a financial analyst. Extract segment-wise revenue and operating income for {corp} of {year} from the provided source material.
{summary}

[Source]
- If the 10-K is unavailable or lacks detail, fallback to the latest 10-Q, earnings release, or investor presentation.
- **Always use actual data from official filings.**
- **Do not invent or hallucinate segments.**

[Output Format]
{{"segment": "Segment Name", "revenue": number, "operating_income": number, "growth_rate": number}}
{{"segment": "Segment Name 2", "revenue": number, "operating_income": number, "growth_rate": number}}
...

[Rules]
- Only output one JSON Lines block.
- Do not add any explanation.
- Numbers must be in Million USD.
- If operating income is missing, set it to null but still report actual segments.
- Never make up segments or revenue figures.
- Output must be valid for `pd.read_json(data, lines=True)`.
"""
    ).content

    return str(segments_json)


def extract_balance_sheet(summary: str) -> str:
    """
    Extract balance sheet information from financial summary.

    Args:
        summary: Financial summary text

    Returns:
        JSON string with balance sheet data
    """
    balance_sheet_json_str = gpt_41_mini.invoke(
        f"""[Goal]
From the provided financial summary text, extract the company-wide balance sheet information.
This includes Total Assets and its key components, Total Liabilities and its key components, and Total Stockholders' Equity and its key components.
Present this data as a single JSON object.

[Source Material]
{summary}

[Output JSON Structure]
{{
  "balance_sheet": {{
    "assets": {{
      "total": "Total Assets Value (string)",
      "components": [
        {{"item": "Asset Component Name (string)", "value": "Amount (string)"}},
        ...
      ]
    }},
    "liabilities": {{
      "total": "Total Liabilities Value (string)",
      "components": [
        {{"item": "Liability Component Name (string)", "value": "Amount (string)"}},
        ...
      ]
    }},
    "equity": {{
      "total": "Total Stockholders\\' Equity Value (string)",
      "components": [
        {{"item": "Equity Component Name (string)", "value": "Amount (string)"}},
        ...
      ]
    }}
  }}
}}

[Rules]
- Only output one JSON object.
- Do not add any explanation before or after the JSON.
- Ensure all monetary values in the JSON are strings.
- If specific components are not found in the source, you can omit them from the 'components' list or use an empty list.
- If a total (e.g., Total Assets) is not found, use "N/A" as its value.
"""
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
            print("Warning: Balance sheet data was empty after parsing.")

    except Exception as e:
        print(
            f"Warning: An unexpected error occurred while processing balance sheet data: {e}"
        )
        print(f"Raw Balance Sheet LLM output: {balance_sheet_json_str}")

    return balance_sheet_table_md
