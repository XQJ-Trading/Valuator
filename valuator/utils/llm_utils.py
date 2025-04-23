import json
import re

from utils.llm_zoo import *


def parse_text(text: str, key_and_description: dict[str, str]) -> dict[str, str]:
    result_json = gpt_41_nano.invoke(
        f"""
Based on these texts & guide, make it as a json formatted string. 
* If there's no value of some keys, just fill out default value without deepthinking.
* DO NOT print the header or footer explanation.
* MUST include code block (```json ```)
<guide>
```json
{key_and_description}
```
<text>
```
{text}
```
"""
    ).content

    try:
        # Strip Markdown code fences if present
        fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result_json, re.S)
        if fence_match:
            clean_json = fence_match.group(1)
        else:
            # Fallback: extract substring between first '{' and last '}'
            start = result_json.find('{')
            end = result_json.rfind('}')
            clean_json = result_json[start:end+1] if start != -1 and end != -1 else result_json
        d = json.loads(clean_json)
    except Exception:
        print("parsing error")
        print("raw output:", result_json)
        d = key_and_description
    finally:
        print("parsed result:", d)
    return d


def quote_text(text: str, where: str) -> str:
    # TODO
    return "lorem ipsum"
