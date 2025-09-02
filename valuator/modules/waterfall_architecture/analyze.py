"""
Projection analysis module for 5-year financial projections.
"""

from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import gpt_41_mini
from valuator.utils.basic_utils import parse_json_from_llm_output
from valuator.modules.waterfall_architecture.financial_analysis import (
    analyze_as_finance,
)
from valuator.modules.waterfall_architecture.ceo_analysis import analyze_as_ceo
from valuator.modules.waterfall_architecture.analysis_utils import (
    setup_logging,
    format_currency_millions,
    create_llm_prompt_template,
    format_markdown_table,
)
import yfinance as yf

# Setup logging
logger = setup_logging()


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
        create_llm_prompt_template(
            "financial_analysis", ceo_report=ceo_report, finance_report=finance_report
        )
    ).content

    # Parse the growth analysis
    try:
        growth_data = parse_json_from_llm_output(growth_analysis)

        # Get balance sheet data
        ticker = yf.Ticker(corp)
        bs = ticker.balance_sheet
        years = "2024"

        total_assets = bs.loc["Total Assets", years].iloc[0]
        total_liabilities = bs.loc[
            "Total Liabilities Net Minority Interest", years
        ].iloc[0]
        total_equity = bs.loc["Stockholders Equity", years].iloc[0]
        logger.info(f"{total_assets}, {total_liabilities}, {total_equity}")

        # Extract current segment revenue data
        current_financials = gpt_41_mini.invoke(
            create_llm_prompt_template(
                "segment_extraction", finance_report=finance_report
            )
        ).content

        current_data = parse_json_from_llm_output(current_financials)
        current_data["assets"] = {
            "total": format_currency_millions(total_assets),
            "liabilities": format_currency_millions(total_liabilities),
            "equity": format_currency_millions(total_equity),
        }

        # Calculate 5-year projections
        projection_data = calculate_projections(growth_data, current_data)

        # Format the output as markdown tables
        return format_projection_report(corp, growth_data, projection_data)

    except Exception as e:
        logger.error(f"Error in analyze function: {str(e)}")
        raise


def calculate_projections(growth_data: dict, current_data: dict) -> list:
    """
    Calculate 5-year financial projections.

    Args:
        growth_data: Growth rates and operating margins data
        current_data: Current financial data

    Returns:
        List of projection data for each year
    """
    tax_rate = 0.25  # 25% tax rate
    years = 5
    projection_data = []

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

            year_data["assets"]["equity"] = prev_year["assets"]["equity"] + net_income
            year_data["assets"]["total"] = year_data["assets"]["equity"] / (
                1 - debt_ratio
            )
            year_data["assets"]["liabilities"] = (
                year_data["assets"]["total"] * debt_ratio
            )

        projection_data.append(year_data)

    return projection_data


def format_projection_report(
    corp: str, growth_data: dict, projection_data: list
) -> str:
    """
    Format projection data as markdown report.

    Args:
        corp: Company name
        growth_data: Growth data for segments
        projection_data: Projection data for each year

    Returns:
        Formatted markdown report
    """
    output = f"# 5-Year Financial Projection for {corp}\n\n"

    # Revenue table
    segment_names = [segment["name"] for segment in growth_data["segments"]]
    headers = ["Year"] + segment_names

    revenue_rows = []
    for year_data in projection_data:
        row = [f"Year {year_data['year']}"]
        for segment_name in segment_names:
            segment_data = next(
                (s for s in year_data["segments"] if s["name"] == segment_name),
                {"revenue": 0},
            )
            row.append(f"${segment_data['revenue']:,.0f}")
        revenue_rows.append(row)

    output += format_markdown_table(headers, revenue_rows, "Revenue by Segment")

    # Income statement table
    income_headers = ["Year", "Operating Income", "Net Income"]
    income_rows = [
        [
            f"Year {year_data['year']}",
            f"${year_data['operating_income']:,.0f}",
            f"${year_data['net_income']:,.0f}",
        ]
        for year_data in projection_data
    ]

    output += "\n" + format_markdown_table(
        income_headers, income_rows, "Income Statement"
    )

    # Balance sheet table
    balance_headers = ["Year", "Total Assets", "Liabilities", "Equity"]
    balance_rows = [
        [
            f"Year {year_data['year']}",
            f"${year_data['assets']['total']:,.0f}",
            f"${year_data['assets']['liabilities']:,.0f}",
            f"${year_data['assets']['equity']:,.0f}",
        ]
        for year_data in projection_data
    ]

    output += "\n" + format_markdown_table(
        balance_headers, balance_rows, "Balance Sheet"
    )

    return output
