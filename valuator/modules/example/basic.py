from langchain_core.messages import SystemMessage, HumanMessage

from utils.basic_utils import *
from utils.llm_utils import *
from utils.llm_zoo import *
from utils.test_runner import append_to_methods


@append_to_methods
def hi(text: str) -> str:
    return f'Hi! You said, {text}'


@append_to_methods
def analyst_ceo_report(company_name: str) -> str:
    s_msg = SystemMessage('''
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
    ''')
    
    h_msg = HumanMessage(content=f'''company_name: {company_name}''')

    result = pplx.invoke([s_msg, h_msg]).content

    return result


@append_to_methods
def basic_finance_report(company_name: str):
    s_msg = SystemMessage(content='''
You are a financial analyst. Given a company name, provide key financial metrics and ratios in a clear, organized format.
In each item, include rating ranged 1(poor) - 5(excellent).

Include:
1. Market Cap
2. P/E Ratio
3. Revenue (TTM)
4. Revenue Growth (YoY)
5. Profit Margin
6. Operating Margin
7. Return on Equity (ROE)
8. Return on Assets (ROA)
9. Current Ratio
10. Debt/Equity Ratio

Format the output as a bulleted list with brief explanations where relevant.
Use the most recent data available.
If exact numbers aren't available, provide reasonable estimates and note them as such.
    ''')

    h_msg = HumanMessage(content=f'''company_name: {company_name}''')

    result = pplx.invoke([s_msg, h_msg]).content
    return result


@append_to_methods
def rating_avg_from_report(report: str) -> str:
    key_and_description = {
        "1": "Market Cap rating, as Integer",
        "2": "P/E Ratio rating, as Integer",
        "3": "Revenue rating, as Integer",
        "4": "Revenue Growth rating, as Integer", 
        "5": "Profit Margin rating, as Integer",
        "6": "Operating Margin rating, as Integer",
        "7": "ROE rating, as Integer",
        "8": "ROA rating, as Integer",
        "9": "Current Ratio rating, as Integer",
        "10": "Debt/Equity rating, as Integer"
    }
    
    parsed = parse_text(report, key_and_description)
    values = [float(v) for v in parsed.values()]
    avg = sum(values) / len(values)

    parsed["average_rating"] = round(avg, 2)
    
    result = json.dumps(parsed)
    return result

@append_to_methods
def rating_assessment(ratings: str):
    ratings_dict = json.loads(ratings)
    avg = ratings_dict["average_rating"]
    
    s_msg = SystemMessage(content='''
Given a set of financial ratings from 1-10 and their average, provide a very brief 1-2 sentence assessment.
Focus on the overall picture indicated by the average score.
Keep it concise and straightforward.
''')

    h_msg = HumanMessage(content=f'''average rating: {avg}''')
    
    result = gpt_41_nano.invoke([s_msg, h_msg]).content
    return result

@append_to_methods
def summary_with_calculation(report: str):
    ratings = rating_avg_from_report(report)
    ratings_dict = json.loads(ratings)
    avg = ratings_dict["average_rating"]
    
    s_msg = SystemMessage(content='''
You are a financial analyst providing a brief summary.
Given a company analysis and its average rating out of 5, provide a 2-3 sentence summary.
Include both qualitative insights from the analysis and mention the numerical rating.
Keep it professional and concise.
''')

    h_msg = HumanMessage(content=f'''
Analysis: {report}
Average Rating: {avg}/5
''')

    result = gpt_41_nano.invoke([s_msg, h_msg]).content
    return result
