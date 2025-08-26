"""
Financial analysis module for company financial data analysis.
"""

import pandas as pd

from valuator.utils.llm_utils import retry
from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.modules.waterfall_architecture.analysis_utils import (
    setup_logging,
    fetch_company_data,
    extract_segments_in_company,
    extract_balance_sheet,
    format_balance_sheet_markdown,
)
from valuator.modules.waterfall_architecture.business_analysis import (
    analyze_as_business,
)
from valuator.utils.llm_zoo import pplx
from langchain_core.messages import SystemMessage, HumanMessage
from valuator.utils.basic_utils import parse_json_from_llm_output

# Setup logging
logger = setup_logging()


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
    segments = extract_segments_in_company(corp, summary, year)

    # Redefine segments based on product-centric classification
    redefined_segments = redefine_segments_product_centric(corp, segments, summary)

    # Get business analysis for each redefined segment
    business_reports = {}
    for segment in redefined_segments["segment"]:
        business_analysis = analyze_as_business(corp, segment)
        business_reports[segment] = business_analysis

        # Update operating income if missing
        if pd.isna(
            redefined_segments.loc[
                redefined_segments["segment"] == segment, "operating_income"
            ].iloc[0]
        ):
            try:
                opm_str = str(business_analysis["segment_analysis"]["estimated_opm"])
                # Handle range format (e.g., "20-25%")
                if "-" in opm_str:
                    opm_str = opm_str.split("-")[0]  # Take the lower bound
                # Remove any non-numeric characters except decimal point
                opm_str = "".join(c for c in opm_str if c.isdigit() or c == ".")
                estimated_opm = float(opm_str)
                revenue = redefined_segments.loc[
                    redefined_segments["segment"] == segment, "revenue"
                ].iloc[0]
                redefined_segments.loc[
                    redefined_segments["segment"] == segment, "operating_income"
                ] = revenue * (estimated_opm / 100)
            except (KeyError, ValueError) as e:
                logger.warning(
                    f"Could not update operating income for segment {segment}: {str(e)}"
                )

    # Validate and fix operating income and margin calculations
    for idx, row in redefined_segments.iterrows():
        revenue = row["revenue"]
        operating_income = row["operating_income"]

        # If operating income is greater than revenue, cap it at 90% of revenue
        if operating_income > revenue:
            redefined_segments.loc[idx, "operating_income"] = revenue * 0.9
            # CLI 로그로 변경
            logger.warning(
                f"Operating income for {row['segment']} was capped at 90% of revenue"
            )

    redefined_segments["margin"] = (
        redefined_segments["operating_income"] / redefined_segments["revenue"] * 100
    )

    # Create financial data table (Segment Performance)
    financial_data = f"""# Financial Data for {corp}

## Segment Performance (Product-Centric Classification)
{redefined_segments.to_markdown()}
"""

    # Extract and format detailed Balance Sheet
    balance_sheet_json_str = extract_balance_sheet(summary)
    balance_sheet_table_md = format_balance_sheet_markdown(balance_sheet_json_str)

    # Create business analysis report
    business_report = create_business_report(corp, business_reports)

    # Combine both reports
    combined_report = f"""{financial_data}

{balance_sheet_table_md} 
---

{business_report}"""

    return combined_report


def create_business_report(corp: str, business_reports: dict) -> str:
    """
    Create business analysis report from segment analyses.

    Args:
        corp: Company name
        business_reports: Dictionary of business analysis reports

    Returns:
        Formatted business report string
    """
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
            logger.warning(f"Error processing analysis for segment {segment}: {str(e)}")
            raise

    return business_report


@retry(tries=3)
def redefine_segments_product_centric(
    corp: str, segments_df: pd.DataFrame, summary: str
) -> pd.DataFrame:
    """
    Redefine SEC-based segments using product-centric classification.

    Args:
        corp: Company name
        segments_df: Original SEC-based segments DataFrame
        summary: Financial summary text

    Returns:
        Redefined segments DataFrame with product-centric classification
    """
    # Prepare SEC segments data for LLM
    sec_segments_data = segments_df.to_dict("records")

    s_msg = SystemMessage(
        """
You are an expert business analyst specializing in product-centric segment classification.
Your task is to review SEC-reported business segments and redefine them based on product types, 
services, or business activities rather than organizational structure.

Guidelines:
- Use SEC segment information as reference, but ensure first-level classification is product-centric
- Primary segment classification should be based on product type, service type, or business type
- When analyzing segments, prioritize product-based categorization over organizational structure
- Maintain revenue and operating income data from original segments
- Combine related segments if they represent similar products/services
- Split segments if they contain distinct product categories

Output Format:
{
    "segments": [
        {
            "segment": "Product-Centric Segment Name",
            "revenue": number,
            "operating_income": number,
            "growth_rate": number,
            "description": "Brief description of products/services in this segment"
        }
    ]
}

Rules:
- All monetary values must be in Million USD
- Final output must be a valid JSON object.
- Preserve original financial data while reclassifying segments
- Ensure total revenue matches original data
- Provide clear rationale for reclassification
"""
    )

    h_msg = HumanMessage(
        content=f"""Company: {corp}

SEC-Reported Segments:
{sec_segments_data}

Financial Summary Context:
{summary}

Please redefine these segments using product-centric classification while preserving financial data."""
    )

    result = pplx.invoke([s_msg, h_msg]).content
    logger.info(f"Redefined segments for {corp}: {result}")

    try:
        # Parse the redefined segments
        redefined_data = parse_json_from_llm_output(result)

        # Convert to DataFrame
        redefined_segments = pd.DataFrame(redefined_data["segments"])

        # INFO log - CLI만 출력
        logger.info(
            f"Redefined segments for {corp}: {len(redefined_segments)} product-centric segments created"
        )

        return redefined_segments

    except Exception as e:
        logger.warning(f"Could not redefine segments for {corp}: {str(e)}")
        raise
