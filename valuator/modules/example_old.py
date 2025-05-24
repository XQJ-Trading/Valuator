import pandas as pd

from valuator.utils.basic_utils import *
from valuator.utils.llm_utils import *
from valuator.utils.llm_zoo import gpt_41, gpt_41_mini, gpt_41_nano, pplx
from valuator.utils.test_runner import append_to_methods
from valuator.data_group.collector import fetch_using_readerLLM, get_report_url


@append_to_methods
def analyze_as_finance(corp: str) -> str:
    year = 2024
    url = get_report_url(corp)
    print(f"source url: {url}")
    source = fetch_using_readerLLM(corp, url)

    summary = ""
    step = 2000
    for s in range(0, len(source), step):
        e = min(s + step, len(source))
        print(f"step: {s} / {len(source)}")
        src = "".join(source[s:e])
        summary += gpt_41_nano.invoke(
            f"""## Role
You are acting as an expert financial analyst specializing in segment performance analysis. Your task is to break down revenue and profitability metrics across different business segments from financial statements.

## Main Task
- You analyze annual financial statements from the provided source material.
- The analysis should cover both company-wide performance and segment-specific metrics.
- When data appears inconsistent or incomplete, note this in your analysis.

## Specific Tasks
1. **Company-wide Financial Overview**:
    - Extract key metrics from the income statement: total revenue, operating income, and operating margin (%)
    - From the balance sheet, collect total assets, total liabilities, and shareholders' equity

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

    segments = gpt_41_mini.invoke(
        f"""[Goal]
- You are a financial analyst. Extract segment-wise revenue and operating income for {corp} of {year} from the provided source material.
{summary}

[Source]
- If the 10-K is unavailable or lacks detail, fallback to the latest 10-Q, earnings release, or investor presentation.
- **Always use actual data from official filings.**
- **Do not invent or hallucinate segments.**

[Output Format]
{{"segment": "Segment Name", "revenue": number, "operating_income": number, "growth_rate: number}}
{{"segment": "Segment Name 2", "revenue": number, "operating_income": number, "growth_rate: number}}
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

    segments = pd.read_json(segments, lines=True)
    segments["margin"] = segments["operating_income"] / segments["revenue"] * 100
    return segments.to_markdown()


@append_to_methods
def analyze_as_ceo(corp: str) -> str:
    result = gpt_41_nano.invoke(
        f"make me a report of {corp} in aspect of ceo brilliance & integrity"
    ).content
    return result


@append_to_methods
def analyze_as_business(corp: str) -> str:
    result = gpt_41_nano.invoke(
        f"make me a report of {corp} in aspect of business act brilliance"
    ).content
    return result


@append_to_methods
def summary(corp: str) -> str:
    finance_report = analyze_as_finance(corp)
    ceo_report = analyze_as_ceo(corp)
    business_report = analyze_as_business(corp)
    result = gpt_41_mini.invoke(
        f"summarize these three contents: 1 - {finance_report} \n\n 2 - {ceo_report} \n\n 3 - {business_report}"
    ).content
    return result
