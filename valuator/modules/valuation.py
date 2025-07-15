"""
Valuation module for DCF (Discounted Cash Flow) analysis.
"""

import json
import logging
from typing import Any

from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import gpt_41_mini, gpt_41
from valuator.utils.llm_utils import HumanMessage, retry
from valuator.utils.basic_utils import parse_json_from_llm_output
from valuator.utils.qt_studio.models.app_state import AppState
from valuator.modules.analyze import analyze

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)
logger = logging.getLogger(__name__)


@retry(tries=3)
def projection(projection_report):
    # Extract projection data
    prompt = HumanMessage(
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
- All monetary values should be numbers without currency symbols and must be fully calculated numeric values (no formulas or expressions).
- Do not output any arithmetic expressions; ensure all sums and calculations are evaluated and presented as numbers.
- Extract data for all 5 years
- If net_income is not available, calculate it as operating_income * 0.75 (assuming 25% tax rate)
- Calculate operating income as sum of segment revenues * operating margins
- Explicitly state in the output that all monetary values are in millions of US dollars (1M$ units).
- Final output must be a valid JSON object.
"""
    )

    #  logger.info(f"Prompt: {prompt}")

    projection_data = gpt_41.invoke([prompt]).content

    logger.info(f"Projection data: {projection_data}")
    # projection_data = json.loads(str(projection_data))
    return projection_data


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
    try:
        params = json.loads(params_json)
        corp = str(params["corp"])
        discount_rate = float(params["discount_rate"])
        terminal_growth = float(params["terminal_growth"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        return f"Error parsing parameters: {str(e)}"

    # Get 5-year projections
    projection_report = analyze(corp)
    projection_data = projection(projection_report)

    try:
        # Clean and parse JSON
        data = parse_json_from_llm_output(projection_data)

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
            output += f"| {i+1} | ${fcf:.0f}M | ${pv:.0f}M |\n"

        output += f"""
## Terminal Value
- Terminal Value: ${dcf_result["terminal_value"]:.0f}M
- Present Value of Terminal Value: ${dcf_result["pv_terminal"]:.0f}M

## Valuation Results
- Enterprise Value: ${dcf_result["enterprise_value"]:.0f}M
- Current Debt: ${float(data["projections"][0]["assets"]["liabilities"]):.0f}M
- Equity Value: ${dcf_result["equity_value"]:.0f}M
"""
        # SUCCESS log - UI 표시
        app_state.add_log(
            level="SUCCESS",
            message=f"DCF Valuation Results for {corp}:\n{output}",
            title=f"[SUCCESS] DCF Valuation for {corp}",
        )
        return output

    except Exception as e:
        # ERROR log - UI 표시
        app_state.add_log(
            level="ERROR",
            message=f"Error in valuation function: {str(e)}",
            title=f"[ERROR] DCF Valuation for {corp}",
        )
        # CLI 로그로 변경
        logger.error(f"Error in valuation function: {str(e)}")
        raise


def calculate_dcf(
    projections: list[dict[str, Any]], discount_rate: float, terminal_growth: float
) -> dict[str, Any]:
    """
    Calculate DCF valuation from projections.

    Args:
        projections: List of projection data
        discount_rate: Discount rate as decimal
        terminal_growth: Terminal growth rate as decimal

    Returns:
        Dictionary with DCF calculation results
    """
    # Calculate free cash flow for each year
    fcf_values = []
    app_state = AppState.get_instance()

    for year in projections:
        # INFO log - CLI만 출력
        logger.info(
            f"Year {year.get('year', 'Unknown')} net_income: {year.get('net_income', 'None')}"
        )

        # Free Cash Flow = Net Income + Depreciation - CapEx - Change in Working Capital
        # For simplicity, we'll use Net Income as a proxy for FCF
        if year["net_income"] is None:
            # Try to calculate net income from operating income
            if year.get("operating_income") is not None:
                # Assuming 25% tax rate
                net_income = float(year["operating_income"]) * 0.75
                logger.info(
                    f"Calculated net_income from operating_income for year {year.get('year', 'Unknown')}: {net_income}"
                )
            else:
                # ERROR log - UI 표시
                app_state.add_log(
                    level="ERROR",
                    message=f"Year {year.get('year', 'Unknown')} has None net_income and no operating_income. Year data: {year}",
                    title="[ERROR] Missing Net Income Data",
                )
                raise ValueError(
                    f"Year {year.get('year', 'Unknown')} has None net_income and no operating_income"
                )
        else:
            net_income = float(year["net_income"])

        fcf = net_income
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
