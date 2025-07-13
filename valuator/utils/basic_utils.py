import os
from getpass import getpass
import dotenv
import json
import re


dotenv.load_dotenv()


def check_api_key(key_name="API_KEY"):
    api_key = os.getenv(key_name)
    if not api_key:
        api_key = getpass(f"{key_name}가 설정되어 있지 않습니다. 입력해주세요: ")
        with open(".env", "a") as env_file:
            env_file.write(f"\n{key_name}={api_key}")
        os.environ[key_name] = api_key
    return api_key


def parse_json_from_llm_output(text):
    """
    LLM 출력에서 코드펜스(```json ... ```) 또는 중괄호 블록을 찾아 json.loads로 파싱합니다.
    실패 시 예외를 발생시킵니다.
    """
    from valuator.utils.qt_studio.models.app_state import AppState

    app_state = AppState.get_instance()

    app_state.add_log(
        level="DEBUG",
        message=f"Input text type: {type(text)}, length: {len(str(text)) if text else 0}",
        title="[DEBUG] JSON Parse Input",
    )

    if isinstance(text, list):
        # list[str|dict] 등은 str로 합침
        text = "\n".join(str(t) for t in text)
        app_state.add_log(
            level="DEBUG",
            message=f"Converted list to string, new length: {len(text)}",
            title="[DEBUG] JSON Parse Input",
        )

    if not isinstance(text, str):
        app_state.add_log(
            level="ERROR",
            message=f"Input must be a string or list of strings, got: {type(text)}",
            title="[ERROR] JSON Parse Input",
        )
        raise ValueError("Input must be a string or list of strings.")

    app_state.add_log(
        level="DEBUG",
        message=f"Original text: {text}",
        title="[DEBUG] JSON Parse Input",
    )

    # 코드펜스 우선
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence_match:
        clean_json = fence_match.group(1)
        app_state.add_log(
            level="DEBUG",
            message="Found JSON in code fence",
            title="[DEBUG] JSON Parse Extraction",
        )
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            clean_json = text[start : end + 1]
            app_state.add_log(
                level="DEBUG",
                message=f"Found JSON in braces: start={start}, end={end}",
                title="[DEBUG] JSON Parse Extraction",
            )
        else:
            clean_json = text
            app_state.add_log(
                level="DEBUG",
                message="No JSON structure found, using full text",
                title="[DEBUG] JSON Parse Extraction",
            )

    app_state.add_log(
        level="DEBUG",
        message=f"Extracted JSON: {clean_json}",
        title="[DEBUG] JSON Parse Extraction",
    )

    # Remove comments from JSON
    # Remove single-line comments (# or //)
    clean_json_before = clean_json
    clean_json = re.sub(r"//.*$", "", clean_json, flags=re.MULTILINE)
    clean_json = re.sub(r"#.*$", "", clean_json, flags=re.MULTILINE)

    if clean_json != clean_json_before:
        app_state.add_log(
            level="DEBUG",
            message="Removed single-line comments from JSON",
            title="[DEBUG] JSON Parse Cleaning",
        )

    # Remove trailing commas before closing braces/brackets
    clean_json_before = clean_json
    clean_json = re.sub(r",(\s*[}\]])", r"\1", clean_json)

    if clean_json != clean_json_before:
        app_state.add_log(
            level="DEBUG",
            message="Removed trailing commas from JSON",
            title="[DEBUG] JSON Parse Cleaning",
        )

    app_state.add_log(
        level="DEBUG",
        message=f"Final cleaned JSON: {clean_json}",
        title="[DEBUG] JSON Parse Final",
    )

    try:
        result = json.loads(clean_json)
        app_state.add_log(
            level="DEBUG",
            message=f"Successfully parsed JSON, result type: {type(result)}",
            title="[DEBUG] JSON Parse Success",
        )
        return result
    except json.JSONDecodeError as e:
        app_state.add_log(
            level="ERROR",
            message=f"JSON parsing failed at line {e.lineno}, column {e.colno}: {e.msg}",
            title="[ERROR] JSON Parse Failure",
        )
        app_state.add_log(
            level="ERROR",
            message=f"Problematic text around error:",
            title="[ERROR] JSON Parse Failure",
        )

        lines = clean_json.split("\n")
        if e.lineno <= len(lines):
            start_line = max(0, e.lineno - 2)
            end_line = min(len(lines), e.lineno + 2)
            error_context = ""
            for i in range(start_line, end_line):
                marker = ">>> " if i == e.lineno - 1 else "    "
                error_context += f"{marker}{i+1:3d}: {lines[i]}\n"

            app_state.add_log(
                level="ERROR", message=error_context, title="[ERROR] JSON Parse Context"
            )

        print(f"ERROR: JSON parsing failed at line {e.lineno}, column {e.colno}")
        print(f"ERROR: Error message: {e.msg}")
        print(f"ERROR: Problematic text around error:")
        lines = clean_json.split("\n")
        if e.lineno <= len(lines):
            start_line = max(0, e.lineno - 2)
            end_line = min(len(lines), e.lineno + 2)
            for i in range(start_line, end_line):
                marker = ">>> " if i == e.lineno - 1 else "    "
                print(f"{marker}{i+1:3d}: {lines[i]}")
        raise
