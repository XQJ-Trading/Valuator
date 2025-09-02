from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.llm_zoo import gemini_2_5_pro, gemini_2_5_flash
from valuator.utils.datalake import cache
from langchain_core.messages import SystemMessage, HumanMessage
import json
import datetime
from valuator.utils.prompt_manager import get_prompt


@append_to_methods()
def create_dcf_form(company_name: str) -> str:
    cache_key = f"fillout.create_form.{company_name}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    s_msg = SystemMessage(
        content=get_prompt(
            "fillout", "create_dcf_form_system", company_name=company_name
        )
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
        content=get_prompt(
            "fillout",
            "fill_dcf_form_system",
            company_name=company_name,
            today=datetime.date.today(),
        )
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
    s_msg = SystemMessage(content=get_prompt("fillout", "calculate_dcf_system"))
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
