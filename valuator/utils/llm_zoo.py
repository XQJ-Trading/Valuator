import os
from typing import Optional

from langchain_perplexity import ChatPerplexity
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from valuator.utils.basic_utils import *


check_api_key("PPLX_API_KEY")
check_api_key("OPENAI_API_KEY")
check_api_key("GOOGLE_API_KEY")

openai_api_key = os.getenv("OPENAI_API_KEY")

gpt_41 = ChatOpenAI(api_key=openai_api_key, model="gpt-4.1")
gpt_41_mini = ChatOpenAI(api_key=openai_api_key, model="gpt-4.1-mini")
gpt_41_nano = ChatOpenAI(api_key=openai_api_key, model="gpt-4.1-nano")


pplx_api_key = os.getenv("PPLX_API_KEY")

google_api_key = os.getenv("GOOGLE_API_KEY")

gemini_2_5_pro = ChatGoogleGenerativeAI(api_key=google_api_key, model="gemini-2.5-pro")
gemini_2_5_flash = ChatGoogleGenerativeAI(api_key=google_api_key, model="gemini-2.5-flash")


class PPLX(ChatPerplexity):
    search_mode: Optional[str] = None
    search_recency_filter: Optional[str] = None

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama-3.1-sonar-small-128k-online",
        temperature: float = 0.7,
        search_mode: str | None = None,
        search_recency_filter: str | None = None,
        **kwargs
    ):
        super().__init__(
            api_key=api_key, model=model, temperature=temperature, **kwargs
        )
        object.__setattr__(self, "search_mode", search_mode)
        object.__setattr__(self, "search_recency_filter", search_recency_filter)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if "extra_body" not in kwargs:
            kwargs["extra_body"] = {}
        if self.search_mode:
            kwargs["extra_body"]["search_mode"] = self.search_mode
        if self.search_recency_filter:
            kwargs["extra_body"]["search_recency_filter"] = self.search_recency_filter
        return super()._generate(messages, stop, run_manager, **kwargs)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        if "extra_body" not in kwargs:
            kwargs["extra_body"] = {}
        if self.search_mode:
            kwargs["extra_body"]["search_mode"] = self.search_mode
        if self.search_recency_filter:
            kwargs["extra_body"]["search_recency_filter"] = self.search_recency_filter
        return super()._stream(messages, stop, run_manager, **kwargs)


pplx = PPLX(
    api_key=pplx_api_key,
    model="sonar",
    temperature=0.0,
    search_mode="sec",
    search_recency_filter="week",  # hour/day/week/month/year 중 하나
)
