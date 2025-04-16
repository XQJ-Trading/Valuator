import json
import os

from langchain_perplexity import ChatPerplexity
from langchain_openai import ChatOpenAI


gpt_41 = None
pplx = None

def init_llms():
    openai_api_key = os.getenv("OPENAI_API_KEY")
    pplx_api_key = os.getenv("PPLX_API_KEY")
    
    global gpt_41, pplx

    if openai_api_key:
        gpt_41 = ChatOpenAI(api_key=openai_api_key, model='gpt-4.1')
    else:
        gpt_41 = None

    if pplx_api_key:
        pplx = ChatPerplexity(api_key=pplx_api_key)
    else:
        pplx = None


def parse_text(text: str, key_and_description: dict[str, str]) -> dict[str, str]:
    result_json = gpt_41.invoke(
f'''
based on full text, parse informations as json.
text:
{text}
keys & description:
{key_and_description}
'''
    ).content

    try:
        d = json.loads(result_json)
    except Exception:
        print('parsing error')
        print('raw output:', result_json)
        d = key_and_description
    finally: 
        print('parsed:', d)
    return d


def quote_text(text: str, where: str) -> str:
    return 'lorem ipsum'