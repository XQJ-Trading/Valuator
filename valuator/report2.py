import os
from datetime import datetime
import shutil
import traceback
from functools import wraps
from dotenv import load_dotenv

from langchain_community.chat_models import ChatPerplexity
from langchain_openai import ChatOpenAI

from config import *

load_dotenv()
##############################################################################################################################

# 실행 시, 새로운 timestamp 기반의 로그 폴더 생성
CURRENT_LOG_DIR = os.path.join("logs", datetime.now().strftime("%y%m%d-%H%M%S"))
os.makedirs(CURRENT_LOG_DIR, exist_ok=True)

LOG_RECORDS = []


def copy_assets_to_log_dir():
    """
    현재 디렉터리의 style.css와 script.js를 CURRENT_LOG_DIR 폴더로 복사합니다.
    """
    assets = ["style.css", "script.js"]
    for asset in assets:
        asset = os.path.join("logs", asset)
        if os.path.exists(asset):
            shutil.copy(asset, CURRENT_LOG_DIR)
            print(f"[INFO] {asset} 파일이 {CURRENT_LOG_DIR}로 복사되었습니다.")
        else:
            print(f"[WARNING] {asset} 파일을 찾을 수 없습니다.")


def log_step_to_html(step_name=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            prompt, output = result
            step = step_name or func.__name__
            # 파일 이름은 단순하게 step.html 로 저장
            filename = os.path.join(CURRENT_LOG_DIR, f"{step}.html")

            html_content = f"""
<html>
  <head>
    <title>{step}</title>
    <link rel="stylesheet" href="style.css">
    <script src="script.js"></script>
  </head>
  <body>
    <div class="container">
      <button class="toggle" onclick="toggleSection('{step}')">[Step] {step}</button>
      <div id="{step}" class="section">
        <h2>Step: {step}</h2>
        <h3>Prompt</h3>
        <pre class="prompt">{prompt}</pre>
        <h3>Output</h3>
        <pre class="output">{output}</pre>
      </div>
    </div>
  </body>
</html>
            """
            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)

            LOG_RECORDS.append((step, prompt, output))
            return output

        return wrapper

    return decorator


def log_full_report():
    # 전체 리포트 파일 이름은 full.html 로 저장
    filename = os.path.join(CURRENT_LOG_DIR, "full.html")

    html_parts = []
    for step_name, prompt, output in LOG_RECORDS:
        html_parts.append(
            f"""
        <hr>
        <h2>Step: {step_name}</h2>
        <h3>Prompt</h3>
        <pre class="prompt">{prompt}</pre>
        <h3>Output</h3>
        <pre class="output">{output}</pre>
        """
        )

    html_content = f"""
<html>
  <head>
    <title>전체 리포트</title>
    <link rel="stylesheet" href="style.css">
    <script src="script.js"></script>
  </head>
  <body>
    <div class="container">
      {''.join(html_parts)}
    </div>
  </body>
</html>
    """
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\n[✅ 전체 리포트 저장됨] → {filename}")


##############################################################################################################################


@log_step_to_html()
def segments_formatter(ticker):
    prompt = f"""Gimme {ticker}'s the primary business segments. For each segment, summarize its name in only 1-2 words. Output your results exactly in this format, with no extra text:

Business 1 : [Segment Name]
Business 2 : [Segment Name]
Business 3 : [Segment Name]
...

Ensure that each segment name is concise (1–2 words) and that your response follows this numbered format exactly"""
    return prompt, llm.pplx.invoke(prompt)


@log_step_to_html()
def cal_segment_revenue(segment_format):
    prompt = f""" context: {segment_format}
"Search the **total revenue** and the percentage breakdown for each business segment, calculate the revenue amount for each segment and present the results in the following format:


Segment Name 1: [Calculated Revenue Amount]
Segment Name 2: [Calculated Revenue Amount]
...
Segment Name n: [Calculated Revenue Amount]


Ensure that each revenue amount is accurately calculated based on the provided percentages and that the results are formatted exactly as shown above."
"""

    return prompt, llm.pplx.invoke(prompt)


@log_step_to_html()
def estimate_segment_growth_rate(segment_format):
    prompt = f"""Given the list of business segments {segment_format} and access to relevant documents for each, analyze the information to estimate the growth rate for each segment over a specified period. Present your findings in the following format:​

Segment Name 1: [Estimated Growth Rate]%

Segment Name 2: [Estimated Growth Rate]%

Segment Name 3: [Estimated Growth Rate]%
-
...

Note: If specific growth rates are not directly provided in the documents, make logical assumptions based on industry trends and historical data to estimate the growth rates for each segment.
    """
    return prompt, llm.pplx.invoke(prompt)


@log_step_to_html()
def estimate_segment_operating_income(segment_format):
    prompt = f"""Given the list of business segments {segment_format} and access to relevant documents for each, analyze the information to estimate the operating income for each segment over a specified period. Present your findings in the following format:​

Segment Name 1: [Estimated operating income]%

Segment Name 2: [Estimated operating income]%

Segment Name 3: [Estimated operating income]%
-
...

Note: If specific operating income are not directly provided in the documents, make logical assumptions based on industry trends and historical data to estimate the operating income for each segment.
"""
    return prompt, llm.pplx.invoke(prompt)


@log_step_to_html()
def parse_segment(segment_format, revenue, growth_rate, operating_income):
    prompt = f"""Given the segment_format and segment_info, parse growth_rate, operating_expenses, initial_revenue to yaml format.
[DATA]
- segment_format: {segment_format}
- growth_rate: {growth_rate}
- revenue: {revenue}
- operating_income: {operating_income}
[TASK]
- Extract and parse initial revenues, annual growth rates, operating_expenses for each business segment.
- Ensure that all relevant information is considered.
- Only include the segment name and its corresponding values.

[OUTPUT FORMAT]
segment: [segment name]
    growth_rate: xx% (e.g., 3-5% → 4%)
    operating_expenses: xx% (e.g., 40-45% → 42.5%)
    initial_revenue: [revenue amount] (e.g. $10.25B where B=Billion, M=Million)
- Exactly as provided in segment_format
- Compress the yaml output without code blocks, removing all spaces and exclude explanations.

[OUTPUT]
segments:
"""
    return prompt, llm.pplx.invoke(prompt)


B = 1e9


class FinanceAnalysis:
    def __init__(self, ticker, year=10, tax=0.25, per=20):
        self.ticker = ticker
        self.year = year
        self.tax = tax
        self.per = per

        self.segments = []
        self.total_revenue = 0
        self.total_operating_income = 0

        self.total_projected_revenue = 0
        self.total_projected_operating_income = 0
        self.total_margin_profit = 0
        self.net_income_before_taxes = 0
        self.net_income_after_taxes = 0
        self.market_capitalization = 0

    def forecast(self):
        self._cal_future_revenue_per_segment()
        self._cal_future_operating_income_per_segment()
        self.net_income_before_taxes = self.total_projected_operating_income
        self.net_income_after_taxes = self.net_income_before_taxes * (1 - self.tax)
        self.market_capitalization = self.net_income_after_taxes * self.per

        print(f"Total Revenue: {self.total_revenue / B}")
        print(f"Total Projected Revenue: {self.total_projected_revenue / B}")
        print(f"Total Operating Income: {self.total_projected_operating_income / B}")
        print(f"Total Margin Profit: {self.total_margin_profit / B}")
        print(f"Net Income Before Taxes: {self.net_income_before_taxes / B}")
        print(f"Net Income After Taxes: {self.net_income_after_taxes / B}")
        print(f"Market Capitalization: {self.market_capitalization / B}")

        # 각 세그먼트의 영업이익률 출력
        for segment in self.segments["segments"]:
            print(f"{segment['segment']}: {segment['profit_margin']:.2f}%")

        return self.segments

    def _cal_future_revenue_per_segment(self, years=10):
        for segment in self.segments["segments"]:
            try:
                initial_revenue_str = segment["initial_revenue"]
                initial_revenue = float(initial_revenue_str[1:-1]) * B
                self.total_revenue += initial_revenue

                growth_rate = self.__parse_percentage(segment["growth_rates"])
                projected_revenue = initial_revenue * (
                    (1 + (growth_rate / 100)) ** years
                )
                self.total_projected_revenue += projected_revenue
                segment.update(
                    {
                        "projected_revenue": projected_revenue,
                    }
                )

            except Exception as e:
                print(f"Error: {segment} {e}")
                error_message = traceback.format_exc()
                print(error_message)

    def _cal_future_operating_income_per_segment(self):
        for segment in self.segments["segments"]:
            try:
                if "projected_revenue" not in segment:
                    raise ValueError(
                        "Projected revenue not calculated. Require projected revenue for operating income calculation."
                    )
                projected_revenue = segment["projected_revenue"]
                operating_income_rate = self.__parse_percentage(
                    segment["operating_income"]
                )
                projected_operating_income = projected_revenue * (
                    operating_income_rate / 100
                )
                profit_margin = (projected_operating_income / projected_revenue) * 100
                self.total_margin_profit += profit_margin
                self.total_projected_operating_income += projected_operating_income
                segment.update(
                    {
                        "projected_operating_income": projected_operating_income,
                        "profit_margin": profit_margin,
                    }
                )
            except Exception as e:
                print(f"Error: {segment} {e}")
                error_message = traceback.format_exc()
                print(error_message)
        self.total_margin_profit /= len(self.segments["segments"])

    def __str__(self, amount):
        return f"${amount / B:.2f}B"

    @property
    def company_info(self):
        return {
            "ticker": self.ticker,
            "year": self.year,
            "tax": self.tax,
            "per": self.per,
            "total_revenue": str(self.total_revenue),
            "total_projected_revenue": str(self.total_projected_revenue),
            "total_margin_profit": str(self.total_margin_profit),
            "total_operating_income": str(self.total_operating_income),
            "net_income_before_taxes": str(self.net_income_before_taxes),
            "net_income_after_taxes": str(self.net_income_after_taxes),
            "market_capitalization": str(self.market_capitalization),
        }

    def __parse_percentage(self, percent):
        values = list(map(float, percent.replace("%", "").split("-")))
        return sum(values) / len(values)


@log_step_to_html()
def arxiv_analyzer(title, ticker, link):
    instruction = r"""Write a report based on the given research paper that includes the following points:
1.	Does the paper introduce innovative ideas that could drive significant changes in the industry, or is it an extension of existing technological progress?
2.	Does the paper suggest that the company’s technological capabilities should be re-evaluated, or does it fall within the expected scope of their advancements?"""
    prompt = f"""title: {title}
    ticker: {ticker}
    link: {link}
    instruction: {instruction}
    """
    return prompt, llm.pplx.invoke(prompt)


def remove_metadata(ai_message):
    del ai_message.usage_metadata
    del ai_message.id
    del ai_message.response_metadata
    return ai_message


@log_step_to_html()
def summarize(company, segments, arxiv):
    years = company["year"]
    ticker = company["ticker"]

    prompt = f"""Generate Comprehensive {years}-Year Outlook Analysis Report for (Ticker: {ticker})
**Input Data**:
- Company Overview: {company}
- Segment Breakdown: {segments}
- Technology Research Summary (arXiv): {arxiv}
---
**Assumptions & Parameters**:
- Discount Rate (WACC): e.g., 9.0%
- Terminal Growth Rate: e.g., 2.5%
- Sensitivity Analysis Range: Key variables ±10%
- Scenario Adjustments: Best Case (+15% growth, +5 percentage points margin) and Worst Case (-15% growth, -5 percentage points margin)
---
**Required Analyses & Execution**:
- Base Financial Projections: Summarize the 10-year projected total Revenue, Operating Income, and Net Income (aggregating all segments) plus the PER-based Market Cap from the input data.

- DCF Valuation:
  - Estimate annual Free Cash Flow (FCF) (e.g., using NOPAT + D&A – Capex – Change in WC).
  - Perform DCF using the given discount rate and terminal growth rate.
  - Present the calculated Intrinsic Value (or range based on sensitivity) and compare it with the PER-based market cap.

- Sensitivity Analysis:
  - Calculate the numerical impact (e.g., percentage or dollar changes) on Year 10 Net Income and DCF Value when key assumptions (AWS & E-commerce growth, overall margin, WACC, terminal growth, PER) change by ±10%.
  - Identify the most impactful assumptions.

- Scenario Analysis:
  - Recompute the 10-year projections (Total Revenue, Operating Income, Net Income) for Base, Best, and Worst Case scenarios.
  - Present the comparative results in a table.

- Segment Contribution Analysis:
  - Determine each segment’s percentage contribution to Total Revenue and Operating Income for Year 1 and Year 10; analyze the shifts in the business mix over time.

- Technology Impact Analysis:
  -Evaluate the innovation, potential industry impact, and strategic implications for Amazon based solely on {arxiv}.
---
**Conclusion & Strategic Recommendations**:
- Summarize key findings from the DCF, sensitivity, scenario, and segment analyses.
- Provide actionable, data-driven strategic recommendations linked directly to these quantitative results and the technology impact assessment.
---
**Report Structure**:
- Executive Summary: Purpose, key figures (Base Financials, DCF value/range, sensitive variables, scenario outcomes), tech impact summary, and recommendations.
- Base Financial Projections & Segment Evolution: Overview of financial forecasts and changes in segment contributions over time.
- Valuation Analysis: Details of FCF calculation, DCF valuation, and comparison with PER-based market cap.
- Risk, Sensitivity & Scenario Analysis: Numerical effects of key variable changes and comparative case results.
- Conclusion & Strategic Recommendations: Synthesis of insights and clear, data-supported strategic guidance.
"""

    return prompt, llm.gpt4o_mini.invoke(prompt)


##############################################################################################################################
class LLMZoo:
    pplx = None
    gpt4o = None
    gpt4o_mini = None


llm = LLMZoo()


def generate_report(title, ticker, link):
    # Perplexity LLM 초기화

    try:
        global llm
        llm.pplx = ChatPerplexity(
            temperature=0,
            pplx_api_key=os.getenv("API_KEY"),
        )
        llm.gpt4o = ChatOpenAI(
            temperature=0, api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o"
        )
        llm.gpt4o_mini = ChatOpenAI(
            temperature=0, api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o-mini"
        )
    except Exception():
        exit(-1)

    """선택한 논문의 제목과 링크를 기반으로 리포트를 생성. 여기가 메인임."""
    copy_assets_to_log_dir()

    # segment_format = segments_formatter(ticker)
    # segment_format = remove_metadata(segment_format)

    # revenue_breakdown = cal_segment_revenue(segment_format)
    # revenue_breakdown = remove_metadata(revenue_breakdown)

    # growth_rate = estimate_segment_growth_rate(segment_format)
    # growth_rate = remove_metadata(growth_rate)

    # operating_income = estimate_segment_operating_income(segment_format)
    # operating_income = remove_metadata(operating_income)

    # segment = parse_segment(
    #     segment_format, growth_rate, revenue_breakdown, operating_income
    # )
    # segment = remove_metadata(segment)
    # segment = yaml.safe_load(segment.content)
    # print(segment)

    forecaster = FinanceAnalysis(ticker="AMZN", year=10, tax=0.25, per=20)
    # example data
    forecaster.segments = {
        "segments": [
            {
                "segment": "E-commerce",
                "growth_rates": "7.45%",
                "operating_income": "40-45%",
                "initial_revenue": "$247B",
            },
            {
                "segment": "AWS",
                "growth_rates": "8.2%",
                "operating_income": "50-55%",
                "initial_revenue": "$107.6B",
            },
            {
                "segment": "Prime",
                "growth_rates": "0.1533%",
                "operating_income": "5-7%",
                "initial_revenue": "$44.4B",
            },
            {
                "segment": "Retail",
                "growth_rates": "0.745%",
                "operating_income": "30-35%",
                "initial_revenue": "$156.1B",
            },
            {
                "segment": "Advertising",
                "growth_rates": "2.62%",
                "operating_income": "5-7%",
                "initial_revenue": "$56.2B",
            },
            {
                "segment": "Services",
                "growth_rates": "5-7%",
                "operating_income": "2-5%",
                "initial_revenue": "$5.8B",
            },
            {
                "segment": "Subscription",
                "growth_rates": "1.533%",
                "operating_income": "5-7%",
                "initial_revenue": "$44.4B",
            },
            {
                "segment": "Physical Stores",
                "growth_rates": "0.21%",
                "operating_income": "2-5%",
                "initial_revenue": "$21.2B",
            },
        ]
    }
    segments = forecaster.forecast()
    company = forecaster.company_info

    if not os.path.exists(f"./{title}.txt"):
        arxiv_result = arxiv_analyzer(title, ticker, link)
        arxiv_result = remove_metadata(arxiv_result)
        with open(f"./{title}.txt", "w") as f:
            f.write(arxiv_result.content)
    else:
        with open(f"./{title}.txt", "r") as f:
            arxiv_result = f.read()
        print("skip to arxiv")
    response = summarize(company, segments, arxiv_result)

    log_full_report()

    return response
