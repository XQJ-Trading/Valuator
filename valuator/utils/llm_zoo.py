import os

from langchain_community.chat_models import ChatPerplexity
from langchain_openai import ChatOpenAI

from valuator.utils.basic_utils import *


check_api_key("PPLX_API_KEY")
check_api_key("OPENAI_API_KEY")

openai_api_key = os.getenv("OPENAI_API_KEY")

gpt_41 = ChatOpenAI(api_key=openai_api_key, model="gpt-4.1")
gpt_41_mini = ChatOpenAI(api_key=openai_api_key, model="gpt-4.1-mini")
gpt_41_nano = ChatOpenAI(api_key=openai_api_key, model="gpt-4.1-nano")


pplx_api_key = os.getenv("PPLX_API_KEY")

pplx = ChatPerplexity(api_key=pplx_api_key, model="sonar", temperature=0.0)
