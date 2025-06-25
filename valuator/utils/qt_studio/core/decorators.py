from valuator.utils.qt_studio.models.app_state import AppState
from functools import wraps
import traceback

def append_to_methods(example_input: str = "Berkshire Hathaway"):
    """
    함수를 시스템에 등록하고, 실행 시 자동으로 로깅하는 데코레이터.
    - example_input: UI에 표시될 함수의 예제 입력값.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # AppState 인스턴스는 래퍼가 실제로 실행될 때 가져옵니다.
            app_state = AppState.get_instance()
            func_name = func.__name__
            
            # 실행 전 로그
            app_state.add_log("INFO", f"Executing '{func_name}' with args: {args}, kwargs: {kwargs}")
            
            try:
                # 원본 함수 실행
                result = func(*args, **kwargs)
                # 성공 로그에는 반환값의 문자열만 정직하게 기록합니다.
                app_state.add_log("SUCCESS", str(result))
                return result
            except Exception as e:
                # 실패 로그
                error_msg = f"Error in '{func_name}': {e}"
                app_state.add_log("ERROR", f"{error_msg}\n\n{traceback.format_exc()}")
                raise # 에러를 다시 발생시켜 상위 호출자가 알 수 있도록 함

        # AppState에 '원본 함수'가 아닌, 로깅 기능이 포함된 'wrapper'를 등록합니다.
        app_state = AppState.get_instance()
        app_state.add_function(wrapper, example=example_input)
        
        return wrapper
    return decorator
