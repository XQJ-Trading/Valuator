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
    if isinstance(text, list):
        # list[str|dict] 등은 str로 합침
        text = "\n".join(str(t) for t in text)
    if not isinstance(text, str):
        raise ValueError("Input must be a string or list of strings.")
    
    # 코드펜스 우선
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence_match:
        clean_json = fence_match.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            clean_json = text[start : end + 1]
        else:
            clean_json = text
    
    # Remove comments from JSON
    # Remove single-line comments (# or //)
    clean_json = re.sub(r'//.*$', '', clean_json, flags=re.MULTILINE)
    clean_json = re.sub(r'#.*$', '', clean_json, flags=re.MULTILINE)
    
    # Remove trailing commas before closing braces/brackets
    clean_json = re.sub(r',(\s*[}\]])', r'\1', clean_json)
    
    try:
        return json.loads(clean_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON parsing failed at line {e.lineno}, column {e.colno}")
        print(f"ERROR: Error message: {e.msg}")
        print(f"ERROR: Problematic text around error:")
        lines = clean_json.split('\n')
        if e.lineno <= len(lines):
            start_line = max(0, e.lineno - 2)
            end_line = min(len(lines), e.lineno + 2)
            for i in range(start_line, end_line):
                marker = ">>> " if i == e.lineno - 1 else "    "
                print(f"{marker}{i+1:3d}: {lines[i]}")
        raise
