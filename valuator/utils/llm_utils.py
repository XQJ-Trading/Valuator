import json

from utils.llm_zoo import *


def parse_text(text: str, key_and_description: dict[str, str]) -> dict[str, str]:
    result_json = gpt_41.invoke(
        f"""
based on full text, parse informations as json.
text:
{text}
keys & description:
{key_and_description}
"""
    ).content

    try:
        d = json.loads(result_json)
    except Exception:
        print("parsing error")
        print("raw output:", result_json)
        d = key_and_description
    finally:
        print("parsed:", d)
    return d


def quote_text(text: str, where: str) -> str:
    # TODO
    return "lorem ipsum"
