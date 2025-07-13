from io import StringIO

import pandas as pd

from valuator.utils.basic_utils import *
from valuator.utils.llm_utils import *
from valuator.utils.llm_zoo import gpt_41, gpt_41_mini, gpt_41_nano, pplx
from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.finsource.collector import fetch_using_readerLLM
from valuator.utils.finsource.sec_collector import get_10k_html_link
from valuator.utils.qt_studio.models.app_state import AppState
from valuator.utils.basic_utils import parse_json_from_llm_output


@append_to_methods()
def analyze_as_finance(corp: str) -> str:
    year = 2024
    url = get_10k_html_link(corp)
    # url = get_report_url(corp)
    print(f"source url: {url}")
    source = fetch_using_readerLLM(corp, url)

    summary = ""
    chunk_size = 2000
    for s in range(0, len(source), chunk_size):
        e = min(s + chunk_size, len(source))
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

    # Fix JSON parsing warning by using StringIO
    segments = pd.read_json(StringIO(segments_json), lines=True)

    # Get business analysis for each segment
    business_reports = {}
    for segment in segments["segment"]:
        business_analysis = analyze_as_business(corp, segment)
        business_reports[segment] = business_analysis

        # Update operating income if missing
        if pd.isna(
            segments.loc[segments["segment"] == segment, "operating_income"].iloc[0]
        ):
            try:
                opm_str = str(business_analysis["segment_analysis"]["estimated_opm"])
                # Handle range format (e.g., "20-25%")
                if "-" in opm_str:
                    opm_str = opm_str.split("-")[0]  # Take the lower bound
                # Remove any non-numeric characters except decimal point
                opm_str = "".join(c for c in opm_str if c.isdigit() or c == ".")
                estimated_opm = float(opm_str)
                revenue = segments.loc[segments["segment"] == segment, "revenue"].iloc[
                    0
                ]
                segments.loc[segments["segment"] == segment, "operating_income"] = (
                    revenue * (estimated_opm / 100)
                )
            except (KeyError, ValueError) as e:
                print(
                    f"Warning: Could not update operating income for segment {segment}: {str(e)}"
                )
                raise

    # Validate and fix operating income and margin calculations
    for idx, row in segments.iterrows():
        revenue = row["revenue"]
        operating_income = row["operating_income"]

        # If operating income is greater than revenue, cap it at 90% of revenue
        if operating_income > revenue:
            segments.loc[idx, "operating_income"] = revenue * 0.9
            print(
                f"Warning: Operating income for {row['segment']} was capped at 90% of revenue"
            )

    segments["margin"] = segments["operating_income"] / segments["revenue"] * 100

    # Create financial data table (Segment Performance)
    financial_data = f"""# Financial Data for {corp}

## Segment Performance
{segments.to_markdown()}
"""

    # --- New: Extract and format detailed Balance Sheet ---
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
    # --- End New: Extract and format detailed Balance Sheet ---

    # Create business analysis report
    business_report = f"""# Business Analysis Report for {corp}

## Business Segment Analysis
"""

    # Add business analysis for each segment
    for segment, analysis in business_reports.items():
        try:
            business_report += f"""
### {segment}
#### Industry Analysis
{analysis.get('industry_analysis', 'No industry analysis available')}

#### Competitive Analysis
{analysis.get('competitive_analysis', 'No competitive analysis available')}

#### Segment Analysis
{analysis.get('segment_analysis', {}).get('description', 'No segment analysis available')}
"""
        except Exception as e:
            print(f"Warning: Error processing analysis for segment {segment}: {str(e)}")
            business_report += f"""
### {segment}
Error processing analysis for this segment.
"""
            raise

    # Combine both reports
    combined_report = f"""{financial_data}

{balance_sheet_table_md} 
---

{business_report}"""

    return combined_report


@append_to_methods()
def analyze_as_ceo(corp: str) -> str:
    s_msg = SystemMessage(
        """
You are an expert investment-analysis assistant.
Your task is to evaluate a public company from the perspective of a long-term investor, focusing on (1) the quality of its CEO & senior leadership team, and (2) the broader organizational culture and governance. Base your work on the philosophies of Philip Fisher, Warren Buffett and Charlie Munger.

Input:
Company name

Output:
Each of output should be in bulleted list format.
Each research of items should be long at least a paragraph
Do not include score.


Stage 1: CEO & Leadership-Team Analysis

Integrity & Transparency (Buffett/Munger: "Integrity first.")

Strategic Vision & Execution (Fisher: deep industry understanding & consistent long-range planning)

Capital-Allocation Skill (Buffett: can $1 retained generate >$1 market value?)

Shareholder-Orientation (alignment of incentives, "skin in the game")

Track Record & Experience (historic outcomes as predictor)

Stage 2: Organizational Culture & Governance

Innovation & R&D Effectiveness (Fisher's "determination to develop new products")

Talent Dynamics (ability to attract & retain top people)

Ethical Climate & Board Interaction (board-management trust, ethical tone)

Decision-making Quality & Adaptability (speed, cross-functional collaboration)

Profit-margin Sustainability & Improvement Efforts (Fisher's margin focus)

Stage 3: Integrated Judgment
• Summarize key strengths, weaknesses, and central risks.
• Give an overall "leadership & culture quality" rating (e.g. Excellent, Good, Fair, Poor).
• Provide a concise investment-recommendation rationale from a long-term, Buffett-/Fisher-style standpoint.
    """
    )

    h_msg = HumanMessage(content=f"""company_name: {corp}""")

    result = pplx.invoke([s_msg, h_msg]).content
    return result


@append_to_methods()
def analyze_as_business(corp: str, segment: str = None) -> dict:
    s_msg = SystemMessage(
        """
You are an expert business analyst specializing in industry and competitive analysis.
Your task is to analyze a company's business segment and provide detailed insights.

Input:
Company name and business segment (if provided)

Output Format:
{
    "industry_analysis": "Detailed analysis of industry characteristics, trends, and vision",
    "competitive_analysis": "Analysis of company's position, strengths, weaknesses, opportunities, and threats",
    "segment_analysis": {
        "description": "Detailed analysis of the specific business segment",
        "market_share": "Estimated market share in this segment",
        "growth_potential": "Growth potential analysis",
        "estimated_opm": "Estimated Operating Profit Margin (as a percentage)"
    }
}

Guidelines:
- Provide detailed, data-driven analysis
- Focus on both qualitative and quantitative aspects
- For OPM estimation, consider industry standards, company history, and competitive position
- Be specific and actionable in your analysis
- The estimated_opm must be a number between 0 and 100
"""
    )

    h_msg = HumanMessage(
        content=f"""company_name: {corp}
business_segment: {segment if segment else "Overall Business"}"""
    )

    result = pplx.invoke([s_msg, h_msg]).content

    # Parse the response into a dictionary
    try:
        # Try to parse as JSON first
        analysis = parse_json_from_llm_output(result)
    except json.JSONDecodeError:
        # If JSON parsing fails, use GPT to parse the text
        analysis = parse_text(
            result,
            {
                "industry_analysis": "Industry analysis details",
                "competitive_analysis": "Competitive analysis details",
                "segment_analysis": "Segment analysis details including estimated_opm",
            },
        )

        # If segment_analysis is a string, try to extract the estimated_opm
        if isinstance(analysis.get("segment_analysis"), str):
            try:
                # Use GPT to extract the estimated_opm from the text
                opm_text = gpt_41_nano.invoke(
                    f"""Extract the estimated Operating Profit Margin (OPM) percentage from this text. 
                    Return only the number, nothing else. If no OPM is mentioned, return 0.
                    
                    Text: {analysis['segment_analysis']}"""
                ).content

                # Convert the extracted text to a float
                estimated_opm = float(opm_text.strip())

                # Create a structured segment_analysis dictionary
                analysis["segment_analysis"] = {
                    "description": analysis["segment_analysis"],
                    "market_share": "Not specified",
                    "growth_potential": "Not specified",
                    "estimated_opm": estimated_opm,
                }
            except (ValueError, Exception) as e:
                print(f"Warning: Could not extract OPM for segment {segment}: {str(e)}")
                analysis["segment_analysis"] = {
                    "description": analysis["segment_analysis"],
                    "market_share": "Not specified",
                    "growth_potential": "Not specified",
                    "estimated_opm": 0,
                }
                raise

    return analysis


@append_to_methods()
def summary(corp: str) -> str:
    finance_report = analyze_as_finance(corp)
    ceo_report = analyze_as_ceo(corp)

    result = gpt_41_mini.invoke(
        f"""Summarize the following analysis:
1. Financial and Business Analysis:
{finance_report}

2. CEO Analysis:
{ceo_report}

Please provide a comprehensive summary that highlights key findings, risks, and opportunities.
"""
    ).content
    return result


@append_to_methods()
def analyze(corp: str) -> str:
    # Get CEO and financial analysis reports
    ceo_report = analyze_as_ceo(corp)
    finance_report = analyze_as_finance(corp)

    # Extract growth rates and operating margins for each segment
    growth_analysis = gpt_41_mini.invoke(
        f"""[Goal]
Analyze the provided reports to extract segment-wise growth rates and operating margins.
Focus on historical data and future projections mentioned in the reports.

[Source Material]
CEO Report:
{ceo_report}

Financial Report:
{finance_report}

[Output Format]
{{
    "segments": [
        {{
            "name": "Segment Name",
            "growth_rate": "Annual growth rate as percentage (e.g., '15.5')",
            "operating_margin": "Operating margin as percentage (e.g., '25.3')"
        }},
        ...
    ]
}}

[Rules]
- Extract growth rates from both historical data and future projections
- If multiple growth rates are mentioned, use the most conservative estimate
- Operating margins should be based on historical data
- All percentages should be numbers without the % symbol
- If data is not available, use reasonable industry averages
"""
    ).content

    # Parse the growth analysis
    try:
        # Clean and parse JSON
        growth_data = parse_json_from_llm_output(growth_analysis)

        # Extract current financial data
        current_financials = gpt_41_mini.invoke(
            f"""[Goal]
Extract the current financial data from the provided report.

[Source Material]
{finance_report}

[Output Format]
{{
    "assets": {{
        "total": "Total Assets value",
        "liabilities": "Total Liabilities value",
        "equity": "Total Equity value"
    }},
    "segments": [
        {{
            "name": "Segment Name",
            "revenue": "Current revenue value"
        }},
        ...
    ]
}}

[Rules]
- All monetary values should be numbers without currency symbols
- Use the most recent available data
- If exact values are not available, use reasonable estimates
"""
        ).content

        # Parse current financials
        current_data = parse_json_from_llm_output(current_financials)

        # Calculate 5-year projections
        tax_rate = 0.25  # 25% tax rate
        years = 5

        # Initialize projection data
        projection_data = []

        # For each year
        for year in range(years):
            year_data = {
                "year": year + 1,
                "assets": {"total": 0, "liabilities": 0, "equity": 0},
                "segments": [],
            }

            # Calculate segment revenues and operating income
            total_operating_income = 0
            for segment in growth_data["segments"]:
                segment_name = segment["name"]
                growth_rate = float(segment["growth_rate"]) / 100
                operating_margin = float(segment["operating_margin"]) / 100

                # Find current revenue for this segment
                current_revenue = next(
                    (
                        float(s["revenue"])
                        for s in current_data["segments"]
                        if s["name"] == segment_name
                    ),
                    0,
                )

                # Calculate projected revenue and operating income
                projected_revenue = current_revenue * (1 + growth_rate) ** (year + 1)
                operating_income = projected_revenue * operating_margin
                total_operating_income += operating_income

                year_data["segments"].append(
                    {"name": segment_name, "revenue": projected_revenue}
                )

            # Calculate net income after tax
            net_income = total_operating_income * (1 - tax_rate)

            # Update balance sheet
            if year == 0:
                # First year: use current values as base
                year_data["assets"]["total"] = float(current_data["assets"]["total"])
                year_data["assets"]["liabilities"] = float(
                    current_data["assets"]["liabilities"]
                )
                year_data["assets"]["equity"] = float(current_data["assets"]["equity"])
            else:
                # Subsequent years: add net income to equity and maintain debt ratio
                prev_year = projection_data[year - 1]
                debt_ratio = (
                    prev_year["assets"]["liabilities"] / prev_year["assets"]["total"]
                )

                year_data["assets"]["equity"] = (
                    prev_year["assets"]["equity"] + net_income
                )
                year_data["assets"]["total"] = year_data["assets"]["equity"] / (
                    1 - debt_ratio
                )
                year_data["assets"]["liabilities"] = (
                    year_data["assets"]["total"] * debt_ratio
                )

            projection_data.append(year_data)

        # Format the output as a markdown table
        output = f"# 5-Year Financial Projection for {corp}\n\n"

        # Revenue table
        output += "## Revenue by Segment\n"
        output += (
            "| Year | "
            + " | ".join(segment["name"] for segment in growth_data["segments"])
            + " |\n"
        )
        output += (
            "|------|" + "|".join(["------" for _ in growth_data["segments"]]) + "|\n"
        )

        for year_data in projection_data:
            row = [f"Year {year_data['year']}"]
            for segment in growth_data["segments"]:
                segment_data = next(
                    (s for s in year_data["segments"] if s["name"] == segment["name"]),
                    {"revenue": 0},
                )
                row.append(f"${segment_data['revenue']:,.0f}")
            output += "| " + " | ".join(row) + " |\n"

        # Balance sheet table
        output += "\n## Balance Sheet\n"
        output += "| Year | Total Assets | Liabilities | Equity |\n"
        output += "|------|--------------|-------------|--------|\n"

        for year_data in projection_data:
            output += f"| Year {year_data['year']} | ${year_data['assets']['total']:,.0f} | ${year_data['assets']['liabilities']:,.0f} | ${year_data['assets']['equity']:,.0f} |\n"

        return output

    except Exception as e:
        print(f"Error in analyze function: {str(e)}")
        return f"Error generating analysis: {str(e)}"


@append_to_methods(
    example_input='{"corp": "BBY", "discount_rate": 0.085, "terminal_growth": 0.025}'
)
def valuation(params_json: str) -> str:
    """
    Perform DCF valuation using 5-year projections.

    Args:
        params_json: JSON string containing parameters:
            {
                "corp": str,  # Company name
                "discount_rate": float,  # e.g., 0.10 for 10%
                "terminal_growth": float  # e.g., 0.03 for 3%
            }

    Example:
        params = {
            "corp": "BBY",  # Best Buy
            "discount_rate": 0.085,  # 8.5% discount rate
            "terminal_growth": 0.025  # 2.5% terminal growth rate
        }
        result = valuation(json.dumps(params))
    """
    app_state = AppState.get_instance()
    # Parse parameters from JSON
    import json

    try:
        params = json.loads(params_json)
        corp = str(params["corp"])
        discount_rate = float(params["discount_rate"])
        terminal_growth = float(params["terminal_growth"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        return f"Error parsing parameters: {str(e)}"

    # Get 5-year projections
    projection_report = analyze(corp)

    # Extract projection data
    projection_data = gpt_41_mini.invoke(
        f"""[Goal]
Extract the financial projection data from the provided report.

[Source Material]
{projection_report}

[Output Format]
{{
    "projections": [
        {{
            "year": 1,
            "revenue": "Total revenue value",
            "operating_income": "Operating income value",
            "net_income": "Net income value",
            "assets": {{
                "total": "Total assets value",
                "liabilities": "Total liabilities value",
                "equity": "Total equity value"
            }}
        }},
        ...
    ]
}}

[Rules]
- All monetary values should be numbers without currency symbols
- Extract data for all 5 years
- Calculate operating income as sum of segment revenues * operating margins
- Calculate net income as operating income * (1 - 0.25) for tax rate
"""
    ).content

    try:
        # Clean and parse JSON
        data = parse_json_from_llm_output(projection_data)

        # Calculate DCF
        def calculate_dcf(projections, discount_rate, terminal_growth):
            # Calculate free cash flow for each year
            fcf_values = []
            for year in projections:
                # Free Cash Flow = Net Income + Depreciation - CapEx - Change in Working Capital
                # For simplicity, we'll use Net Income as a proxy for FCF
                fcf = float(year["net_income"])
                fcf_values.append(fcf)

            # Calculate present value of projected cash flows
            pv_fcf = []
            for i, fcf in enumerate(fcf_values):
                pv = fcf / ((1 + discount_rate) ** (i + 1))
                pv_fcf.append(pv)

            # Calculate terminal value
            last_fcf = fcf_values[-1]
            terminal_value = (last_fcf * (1 + terminal_growth)) / (
                discount_rate - terminal_growth
            )
            pv_terminal = terminal_value / ((1 + discount_rate) ** len(fcf_values))

            # Calculate enterprise value
            enterprise_value = sum(pv_fcf) + pv_terminal

            # Get current debt
            current_debt = float(projections[0]["assets"]["liabilities"])

            # Calculate equity value
            equity_value = enterprise_value - current_debt

            return {
                "fcf_values": fcf_values,
                "pv_fcf": pv_fcf,
                "terminal_value": terminal_value,
                "pv_terminal": pv_terminal,
                "enterprise_value": enterprise_value,
                "equity_value": equity_value,
            }

        # Perform DCF calculation
        dcf_result = calculate_dcf(data["projections"], discount_rate, terminal_growth)

        # Format output
        output = f"""# DCF Valuation for {corp}

## Assumptions
- Discount Rate: {discount_rate*100:.1f}%
- Terminal Growth Rate: {terminal_growth*100:.1f}%
- Tax Rate: 25%

## Free Cash Flow Projections
| Year | Free Cash Flow | Present Value |
|------|----------------|---------------|
"""

        for i, (fcf, pv) in enumerate(
            zip(dcf_result["fcf_values"], dcf_result["pv_fcf"])
        ):
            output += f"| {i+1} | ${fcf:,.0f} | ${pv:,.0f} |\n"

        output += f"""
## Terminal Value
- Terminal Value: ${dcf_result["terminal_value"]:,.0f}
- Present Value of Terminal Value: ${dcf_result["pv_terminal"]:,.0f}

## Valuation Results
- Enterprise Value: ${dcf_result["enterprise_value"]:,.0f}
- Current Debt: ${float(data["projections"][0]["assets"]["liabilities"]):,.0f}
- Equity Value: ${dcf_result["equity_value"]:,.0f}
"""
        app_state.add_log(
            level="SUCCESS",
            message=f"DCF Valuation Results for {corp}:\n{output}",
            title=f"[SUCCESS] DCF Valuation for {corp}",
        )
        return output

    except Exception as e:
        app_state.add_log(
            level="ERROR",
            message=f"Error in valuation function: {str(e)}",
            title=f"[ERROR] DCF Valuation for {corp}",
        )
        print(f"Error in valuation function: {str(e)}")
        return f"Error performing valuation: {str(e)}"
