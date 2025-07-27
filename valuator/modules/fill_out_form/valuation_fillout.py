from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import gemini_2_5_pro, gemini_2_5_flash
from valuator.utils.datalake import cache
from langchain_core.messages import SystemMessage, HumanMessage
import json
import datetime


@append_to_methods()
def create_dcf_form(company_name: str) -> str:
    cache_key = f"fillout.create_form.{company_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    s_msg = SystemMessage(
        content="""

You are a highly successful and experienced individual investor.
I am planning to conduct a company analysis and valuation for AAPL, primarily using a DCF (Discounted Cash Flow) approach.
Uniquely, instead of the typical 5-year forecast model, I want to use a table that includes aggressively designed 15-year forecast figures. However, you do not need to fill in the contents of the table. Please design a valuation form for me in the format of a spreadsheet.
"""
    )
    h_msg = HumanMessage(content=f"company_name: {company_name}")
    result = gemini_2_5_pro.invoke([s_msg, h_msg]).content
    cache.set(cache_key, result)
    return result


@append_to_methods()
def fill_dcf_form(form_and_company: str) -> str:
    """
    Receives a JSON string with "form" and "company_name", and fills out the form for the company.
    """
    data = json.loads(form_and_company)
    form = data["form"]
    company_name = data["company_name"]
    cache_key = f"fillout.filled_form.{company_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    s_msg = SystemMessage(
        content=f"""
You are a highly successful and experienced individual investor.
I am planning to conduct a DCF (Discounted Cash Flow) valuation for {company_name} by filling out the form below.
Please make sure to use the most up-to-date information available as of {datetime.date.today()} when conducting your research and filling out the form.
You do not need to perform the actual DCF calculation. Instead, your task is to thoroughly fill out the form based on sufficient research. For any complex calculations, you can leave them as math expressions so that they can be calculated later.
It is important to begin filling out the table only after conducting sufficiently extensive research.
"""
    )
    h_msg = HumanMessage(content=form)
    result = gemini_2_5_pro.invoke([s_msg, h_msg]).content
    cache.set(cache_key, result)
    return result


@append_to_methods()
def calculate_dcf_from_form(form: str) -> str:
    cache_key = f"fillout.calculated.{hash(form)}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    s_msg = SystemMessage(
        content="""
너는 금융 기초지식이 풍부한 프로그래머야. 다음의 자료에 기반해서, dcf valuation의 결과를 제시하도록 해.
"""
    )
    h_msg = HumanMessage(content=form)
    result = gemini_2_5_flash.invoke([s_msg, h_msg]).content
    cache.set(cache_key, result)
    return result


@append_to_methods()
def dcf_valuation_report(ticker: str) -> str:
    """
    Generates a DCF valuation report for a given stock ticker.
    """
    cache_key = f"fillout.report.{ticker}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    # 1. Create form
    form_template = create_dcf_form(ticker)

    # 2. Fill out form
    fill_input = json.dumps({"form": form_template, "company_name": ticker})
    filled_form = fill_dcf_form(fill_input)

    # 3. Calculate from filled form
    report = calculate_dcf_from_form(filled_form)
    cache.set(cache_key, report)
    return report