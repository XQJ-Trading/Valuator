import json
import os

from langchain_community.chat_models import ChatPerplexity
from langchain_openai import ChatOpenAI


def parse_text(text: str, key_and_description: dict[str, str]) -> dict[str, str]:
    result = '{"name": "Alice", "age": 30, "is_student": false}'
    d = json.loads(result)
    
    return d


def quote_text(text: str, where: str) -> str:
    return 'lorem ipsum'