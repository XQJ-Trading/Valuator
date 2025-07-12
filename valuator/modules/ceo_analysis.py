"""
CEO analysis module for leadership and governance evaluation.
"""

import logging
from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import pplx
from valuator.utils.llm_utils import SystemMessage, HumanMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)
logger = logging.getLogger(__name__)

@append_to_methods()
def analyze_as_ceo(corp: str) -> str:
    """
    Evaluate a public company from the perspective of a long-term investor,
    focusing on CEO & senior leadership team quality and organizational culture.

    Args:
        corp: Company name

    Returns:
        CEO and leadership analysis report
    """
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
    return str(result)
