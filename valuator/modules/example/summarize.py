"""
Summary analysis module for comprehensive company analysis summaries.
"""

from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import gpt_41_mini
from valuator.modules.example.financial_analysis import analyze_as_finance
from valuator.modules.example.ceo_analysis import analyze_as_ceo


@append_to_methods()
def summary(corp: str) -> str:
    """
    Generate a comprehensive summary of financial and CEO analysis.

    Args:
        corp: Company name

    Returns:
        Comprehensive summary report
    """
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

    return str(result)
