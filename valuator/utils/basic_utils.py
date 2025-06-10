import os
from getpass import getpass
import dotenv


dotenv.load_dotenv()


def check_api_key(key_name="API_KEY"):
    api_key = os.getenv(key_name)
    if not api_key:
        api_key = getpass(f"{key_name}가 설정되어 있지 않습니다. 입력해주세요: ")
        with open(".env", "a") as env_file:
            env_file.write(f"\n{key_name}={api_key}")
        os.environ[key_name] = api_key
    return api_key
