import os
import click
from datetime import datetime
import shutil
from functools import wraps
from dotenv import load_dotenv

from langchain_community.chat_models import ChatPerplexity
from langchain_openai import ChatOpenAI

from config import *

##############################################################################################################################

# 실행 시, 새로운 timestamp 기반의 로그 폴더 생성
CURRENT_LOG_DIR = os.path.join("logs", datetime.now().strftime("%y%m%d-%H%M%S"))
os.makedirs(CURRENT_LOG_DIR, exist_ok=True)

LOG_RECORDS = []

def copy_assets_to_log_dir():
    """
    현재 디렉터리의 style.css와 script.js를 CURRENT_LOG_DIR 폴더로 복사합니다.
    """
    assets = [TEMPLATE_JS_PATH, TEMPLATE_CSS_PATH]
    for asset in assets:
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
        html_parts.append(f"""
        <hr>
        <h2>Step: {step_name}</h2>
        <h3>Prompt</h3>
        <pre class="prompt">{prompt}</pre>
        <h3>Output</h3>
        <pre class="output">{output}</pre>
        """)

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

class LLMZoo:
    pplx =  None
    gpt4o = None

llm = LLMZoo()

def template(parameter1, parameter2):
    instruction = r"""asdf"""
    prompt = f"""parameter1: {parameter1}
    parameter2: {parameter2}
    instruction: {instruction}
    """
    return prompt, llm.pplx.invoke(prompt)


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
def segment_revenue_calculator(segment_format):
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
    prompt = f"""segment format: {segment_format}
    Given the list of business segments and access to relevant documents for each, analyze the information to estimate the growth rate for each segment over a specified period. Present your findings in the following format:​

Segment Name 1: [Estimated Growth Rate]%

Segment Name 2: [Estimated Growth Rate]%

Segment Name 3: [Estimated Growth Rate]%

...

Note: If specific growth rates are not directly provided in the documents, make logical assumptions based on industry trends and historical data to estimate the growth rates for each segment.
    """
    return prompt, llm.pplx.invoke(prompt)


@log_step_to_html()
def revenue_forecaster(growth_rate, revenue_breakdown, arxiv_result):
    instruction = r"""
    ​Given the initial revenue values and annual growth rates for each business segment, calculate the projected revenue for each segment after 10 years. Present the results in the following format:​

    Segment Name 1: Initial Revenue = $X million, Growth Rate = Y%, Projected Revenue after 10 years = $Z million​

    Segment Name 2: Initial Revenue = $A million, Growth Rate = B%, Projected Revenue after 10 years = $C million​

    ...​

    Note: Assume that the growth rate is compounded annually. Use the formula:​

    Projected Revenue=Initial Revenue×(1+Growth Rate100)10\text{Projected Revenue} = \text{Initial Revenue} \times (1 + \frac{\text{Growth Rate}}{100})^{10}Projected Revenue=Initial Revenue×(1+100Growth Rate​)10

    to calculate the projected revenue for each segment.
    
    if needed, arxiv_result can revaluate this revenue forecast."""

    prompt = f"""growth_rate: {growth_rate}
    revenue_breakdown: {revenue_breakdown}
    arxiv_result: {arxiv_result}
    instruction: {instruction}
    """
    return prompt, llm.pplx.invoke(prompt)


@log_step_to_html()
def segment_profit_margin_allocator(revenue_breakdown):
    instruction = r"""Given the total revenue and the operating income of a company, along with the revenue distribution across its business segments as follows:​

Segment 1: X% of revenue​

Segment 2: Y% of revenue​

Segment 3: Z% of revenue​

...

Calculate the operating profit margin for each segment. Ensure that the sum of the operating incomes from all segments equals the total operating income. Present the operating profit margin for each segment in the following format:​

Segment 1: [Operating Profit Margin]%​

Segment 2: [Operating Profit Margin]%​

Segment 3: [Operating Profit Margin]%​

...

Note: If specific operating profit margins for each segment are not provided, make logical assumptions based on industry standards to ensure that the total operating income aligns with the provided figure."""
    prompt = f"""revenue_breakdown: {revenue_breakdown}
    instruction: {instruction}
    """
    return prompt, llm.pplx.invoke(prompt)


@log_step_to_html()
def market_cap_calculator(revenue_forecast, margin_analysis):
    instruction = r"""Given the initial revenues, annual growth rates, and operating profit margins for each business segment, perform the following calculations:​a





Calculate the projected revenue for each segment after 10 years:

Projected Revenue=Initial Revenue×(1+Growth Rate100)10\text{Projected Revenue} = \text{Initial Revenue} \times (1 + \frac{\text{Growth Rate}}{100})^{10}Projected Revenue=Initial Revenue×(1+100Growth Rate​)10



Determine the operating income for each segment:

Operating Income=Projected Revenue×Operating Profit Margin100\text{Operating Income} = \text{Projected Revenue} \times \frac{\text{Operating Profit Margin}}{100}Operating Income=Projected Revenue×100Operating Profit Margin​



Sum the operating incomes to obtain the total operating income:

Total Operating Income=∑Operating Income of all segments\text{Total Operating Income} = \sum \text{Operating Income of all segments}Total Operating Income=∑Operating Income of all segments



Calculate the net income before taxes:

Net Income Before Taxes=Total Operating Income\text{Net Income Before Taxes} = \text{Total Operating Income}Net Income Before Taxes=Total Operating Income



Compute the net income after taxes (assuming a tax rate of 25%):

Net Income After Taxes=Net Income Before Taxes×0.75\text{Net Income After Taxes} = \text{Net Income Before Taxes} \times 0.75Net Income After Taxes=Net Income Before Taxes×0.75



Estimate the market capitalization by applying a multiplier of 20 to the net income after taxes:

Market Capitalization=Net Income After Taxes×20\text{Market Capitalization} = \text{Net Income After Taxes} \times 20Market Capitalization=Net Income After Taxes×20

Note: This methodology assumes a constant tax rate of 25% and a valuation multiplier (P/E ratio) of 20. Adjust these assumptions as necessary based on specific industry standards or company data."""
    prompt = f"""revenue_forecast: {revenue_forecast}
    margin_analysis: {margin_analysis}
    instruction: {instruction}
    """
    return prompt, llm.gpt4o.invoke(prompt)


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


##############################################################################################################################

def generate_report(title, ticker, link):
    # Perplexity LLM 초기화
    try:
        global llm
        llm.pplx = ChatPerplexity(temperature=0, pplx_api_key=os.getenv("PPLX_API_KEY"),)
        llm.gpt4o = ChatOpenAI(temperature=0, api_key=os.getenv("OPENAI_API_KEY"), model='gpt-4o')
    except Exception():
        exit(-1)

    """선택한 논문의 제목과 링크를 기반으로 리포트를 생성. 여기가 메인임."""
    copy_assets_to_log_dir()

    segment_format = segments_formatter(ticker)

    revenue_breakdown = segment_revenue_calculator(segment_format)
    
    growth_rate = estimate_segment_growth_rate(segment_format)

    arxiv_result = arxiv_analyzer(title, ticker, link)

    revenue_forecast = revenue_forecaster(growth_rate, revenue_breakdown, arxiv_result)

    margin_analysis = segment_profit_margin_allocator(revenue_breakdown)

    response = market_cap_calculator(revenue_forecast, margin_analysis)

    log_full_report()

    return response
