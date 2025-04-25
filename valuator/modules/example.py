from utils.basic_utils import *
from utils.llm_utils import *
from utils.llm_zoo import *
from utils.test_runner import append_to_methods




@append_to_methods
def analyze_as_finance(data: dict):
    corp = data['corp']
    result = gpt_41_nano.invoke(f'make me a report of {corp} in aspect of finance').content
    return {'report': result}


@append_to_methods
def analyze_as_ceo(data: dict):
    corp = data['corp']
    result = gpt_41_nano.invoke(f'make me a report of {corp} in aspect of ceo brilliance & integrity').content
    return {'report': result}


@append_to_methods
def analyze_as_business(data: dict):
    corp = data['corp']
    result = gpt_41_nano.invoke(f'make me a report of {corp} in aspect of business act brilliance').content
    return {'report': result}


@append_to_methods
def summary(data: dict):
    finance_report = analyze_as_finance(data)['report']
    ceo_report = analyze_as_ceo(data)['report']
    business_report = analyze_as_business(data)['report']
    result = gpt_41_mini.invoke(
        f'summarize these three contents: 1 - {finance_report} \n\n 2 - {ceo_report} \n\n 3 - {business_report}').content
    return {'summary': result}