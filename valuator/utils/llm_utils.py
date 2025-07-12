import json
import re
import logging
import time
import inspect
from functools import wraps
import traceback

from langchain_core.messages import SystemMessage, HumanMessage

from valuator.utils.llm_zoo import *

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)
logger = logging.getLogger(__name__)


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
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", result_json, re.S)
        if fence_match:
            clean_json = fence_match.group(1)
        else:
            # Fallback: extract substring between first '{' and last '}'
            start = result_json.find("{")
            end = result_json.rfind("}")
            clean_json = (
                result_json[start : end + 1]
                if start != -1 and end != -1
                else result_json
            )
        d = json.loads(clean_json)
    except Exception:
        print("parsing error")
        print("raw output:", result_json)
        d = key_and_description
    finally:
        print("parsed result:", d)
    return d


def translate(text: str, /, mode="invoke") -> str:
    s_msg = SystemMessage(
        """
    You are a professional translator in finance domain. 
    Given English text, you should translate it into Korean text.
    Text meaning must not be contaminated and changed.
    Format and blank lines should be strictly unchanged.
    """
    )
    h_msg = HumanMessage(text)
    result = gpt_41_mini.invoke([s_msg, h_msg]).content
    return result


def retry(tries: int):
    """
    retry help decorator.
    :param retry_num: the retry num; retry sleep sec
    :return: decorator
    """

    def decorator(func):
        """decorator"""
        if hasattr(func, "_is_retry_decorated"):
            # 이미 retry 데코레이터가 적용된 경우, 추가 적용을 방지합니다.
            return func

        # preserve information about the original function,
        # or the func name will be "wrapper" not "func"
        @wraps(func)
        def wrapper(*args, **kwargs):
            """wrapper"""
            for attempt in range(tries):
                try:
                    return func(
                        *args, **kwargs
                    )  # should return the raw function's return value
                except Exception as err:  # pylint: disable=broad-except
                    logger.error(err)
                    traceback.print_exc()
                logger.warning("Trying attempt %s of %s.", attempt + 1, tries)
            logger.error("func %s retry failed", func)

        wrapper._is_retry_decorated = True
        return wrapper

    return decorator


def timeit(func, verbose=False):
    @wraps(func)
    def timeit_wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        total_time = end_time - start_time
        # first item in the args, ie `args[0]` is `self`, args[1] is `wrapper in retry`
        # 호출 스택에서 현재 함수의 바로 위에 있는 함수(상위 함수)를 찾습니다.
        caller = inspect.stack()[2]
        caller_name = caller.function

        logger.debug(f"Function {caller_name} took {total_time:.4f} seconds")
        return result

    return timeit_wrapper
