"""
Financial analysis module for company financial data analysis.
"""

from io import StringIO
import pandas as pd

from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.modules.analysis_utils import (
    fetch_company_data,
    extract_segments_in_company,
    extract_balance_sheet,
    format_balance_sheet_markdown,
)
from valuator.modules.business_analysis import analyze_as_business


@append_to_methods()
def analyze_as_finance(corp: str) -> str:
    """
    Analyze company financial data including segments and balance sheet.

    Args:
        corp: Company ticker or name

    Returns:
        Comprehensive financial analysis report
    """
    year = 2024

    summary = fetch_company_data(corp)
    segments_json = extract_segments_in_company(corp, summary, year)
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

    # Extract and format detailed Balance Sheet
    balance_sheet_json_str = extract_balance_sheet(summary)
    balance_sheet_table_md = format_balance_sheet_markdown(balance_sheet_json_str)

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

    # Combine both reports
    combined_report = f"""{financial_data}

{balance_sheet_table_md} 
---

{business_report}"""

    return combined_report
