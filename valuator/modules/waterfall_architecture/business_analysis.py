"""
Business analysis module for industry and competitive analysis.
"""

import json
from typing import Dict, Optional, Any

from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import pplx, gpt_41_nano
from langchain_core.messages import SystemMessage, HumanMessage
from valuator.utils.basic_utils import parse_json_from_llm_output
from valuator.utils.llm_utils import parse_text
from valuator.modules.waterfall_architecture.analysis_utils import (
    setup_logging,
)

# Setup logging
logger = setup_logging()


@append_to_methods()
def analyze_as_business(corp: str, segment: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze a company's business segment and provide detailed insights.

    Args:
        corp: Company name
        segment: Business segment name (optional)

    Returns:
        Dictionary with industry, competitive, and segment analysis
    """
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
- The estimated_opm must be a number between 0 and 100.
- Use SEC segment information as reference, but ensure first-level classification is product-centric
- Primary segment classification should be based on product type, service type, or business type
- When analyzing segments, prioritize product-based categorization over organizational structure
"""
    )

    h_msg = HumanMessage(
        content=f"""company_name: {corp}
SEC-given business_segment : {segment if segment else "Overall Business"}"""
    )

    result = pplx.invoke([s_msg, h_msg]).content

    # INFO log - CLI만 출력
    logger.info(f"Business analysis result for {corp}: {result[:200]}...")

    analysis: Dict[str, Any] = {}
    try:
        analysis = parse_json_from_llm_output(result)
    except json.JSONDecodeError:
        # If JSON parsing fails, use GPT to parse the text
        if isinstance(result, str):
            analysis = parse_text(
                result,
                {
                    "industry_analysis": "Industry analysis details",
                    "competitive_analysis": "Competitive analysis details",
                    "segment_analysis": "Segment analysis details including estimated_opm",
                },
            )
        else:
            analysis = {
                "industry_analysis": "Analysis not available",
                "competitive_analysis": "Analysis not available",
                "segment_analysis": "Analysis not available",
            }

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
                if isinstance(opm_text, str):
                    estimated_opm = float(opm_text.strip())
                else:
                    estimated_opm = 0

                # Create a structured segment_analysis dictionary
                analysis["segment_analysis"] = {
                    "description": analysis["segment_analysis"],
                    "market_share": "Not specified",
                    "growth_potential": "Not specified",
                    "estimated_opm": estimated_opm,
                }
            except (ValueError, Exception) as e:
                logger.warning(f"Could not extract OPM for segment {segment}: {str(e)}")
                raise

    return analysis
