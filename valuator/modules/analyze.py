"""
Projection analysis module for 5-year financial projections.
"""

import logging
from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import gpt_41_mini
from valuator.utils.basic_utils import parse_json_from_llm_output
from valuator.modules.financial_analysis import analyze_as_finance
from valuator.modules.ceo_analysis import analyze_as_ceo
import yfinance as yf

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)
logger = logging.getLogger(__name__)


@append_to_methods()
def analyze(corp: str) -> str:
    """
    Generate 5-year financial projections based on financial and CEO analysis.

    Args:
        corp: Company name

    Returns:
        5-year financial projection report
    """
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
- Explicitly state in the output that all monetary values are in millions of US dollars (1M$ units).
"""
    ).content

    # Parse the growth analysis
    try:
        # Clean and parse JSON
        growth_data = parse_json_from_llm_output(growth_analysis)

        ticker = yf.Ticker(corp)
        bs = ticker.balance_sheet
        years = "2024"

        total_assets = bs.loc["Total Assets", years].iloc[0]
        total_liabilities = bs.loc[
            "Total Liabilities Net Minority Interest", years
        ].iloc[0]
        total_equity = bs.loc["Stockholders Equity", years].iloc[0]
        logger.info(f"{total_assets}, {total_liabilities}, {total_equity}")

        # For segment revenue, fallback to LLM extraction as before
        current_financials = gpt_41_mini.invoke(
            f"""[Goal]
Extract the current segment revenue data from the provided report.

[Source Material]
{finance_report}

[Output Format]
{{
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
- Explicitly state in the output that all monetary values are in millions of US dollars (1M$ units).
"""
        ).content

        current_data = parse_json_from_llm_output(current_financials)
        current_data["assets"] = {
            "total": float(total_assets) / 1_000_000,  # convert to millions
            "liabilities": float(total_liabilities) / 1_000_000,
            "equity": float(total_equity) / 1_000_000,
        }

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

            # Add net income to year data
            year_data["net_income"] = net_income
            year_data["operating_income"] = total_operating_income

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

        # Income statement table
        output += "\n## Income Statement\n"
        output += "| Year | Operating Income | Net Income |\n"
        output += "|------|------------------|------------|\n"

        for year_data in projection_data:
            output += f"| Year {year_data['year']} | ${year_data['operating_income']:,.0f} | ${year_data['net_income']:,.0f} |\n"

        # Balance sheet table
        output += "\n## Balance Sheet\n"
        output += "| Year | Total Assets | Liabilities | Equity |\n"
        output += "|------|--------------|-------------|--------|\n"

        for year_data in projection_data:
            output += f"| Year {year_data['year']} | ${year_data['assets']['total']:,.0f} | ${year_data['assets']['liabilities']:,.0f} | ${year_data['assets']['equity']:,.0f} |\n"

        return output

    except Exception as e:
        # CLI 로그로 변경
        logger.error(f"Error in analyze function: {str(e)}")
        raise
