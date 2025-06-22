from PyQt5.QtCore import QObject, pyqtSignal
from valuator.utils.qt_studio.models.app_state import AppState
import traceback

class MainViewModel(QObject):
    """
    View와 Model을 중재하는 ViewModel.
    - Model의 변경 시그널을 받아 View를 업데이트하기 위한 시그널을 보냄.
    - View의 사용자 액션을 받아 Model의 상태를 변경.
    """
    # Signals to View
    function_list_updated = pyqtSignal(list)
    log_list_updated = pyqtSignal(list)
    central_view_changed = pyqtSignal(object) # View 위젯을 전달
    function_execution_result = pyqtSignal(str)

    def __init__(self, model: AppState):
        super().__init__()
        self._model = model
        self._selected_function = None

        # Connect to model signals
        self._model.functions_changed.connect(self.update_function_list)
        self._model.logs_changed.connect(self.update_log_list)

    def load_initial_data(self):
        """ 초기 데이터 로드를 트리거합니다. """
        self.update_function_list()
        self.update_log_list()
        self._model.add_log("INFO", "Application started.")

    def update_function_list(self):
        functions = self._model.get_all_functions()
        self.function_list_updated.emit(functions)

    def update_log_list(self):
        logs = self._model.get_all_logs()
        print(f"[DEBUG] ViewModel: Received log update signal. Passing {len(logs)} logs to View.")
        self.log_list_updated.emit(logs)

    def select_function(self, func):
        """ 사용자가 function list에서 함수를 선택했을 때 호출됩니다. """
        self._selected_function = func
        self._model.add_log("INFO", f"Function '{func.__name__}' selected.")
        # 중앙 뷰어 변경 시그널을 보냅니다. (실제 View는 main_window에서 생성)
        self.central_view_changed.emit(func)

    def execute_selected_function(self, input_text: str):
        """ 선택된 함수를 실행합니다. """
        if not self._selected_function:
            self._model.add_log("ERROR", "No function selected to execute.")
            return

        func_name = self._selected_function.__name__
        # 실행 로깅은 이제 데코레이터가 담당하므로 아래 라인은 제거하거나 주석 처리합니다.
        # self._model.add_log("INFO", f"Executing '{func_name}' with input: {input_text[:50]}...")
        
        try:
            # 데코레이터가 적용된 함수를 직접 실행합니다.
            result = self._selected_function(input_text)
            self.function_execution_result.emit(str(result))
        except Exception as e:
            # 데코레이터가 에러 로그를 남겼으므로, ViewModel은 UI 피드백에 집중합니다.
            # 포맷된 에러 메시지를 중앙 뷰어의 결과창으로 보냅니다.
            error_message = f"An error occurred:\n\n{e}\n\n--- TRACEBACK ---\n{traceback.format_exc()}"
            self.function_execution_result.emit(error_message)

    def get_function_example(self, func_name: str) -> str:
        """ Model로부터 함수의 예제 입력을 가져옵니다. """
        return self._model.get_function_example(func_name)

    def clear_logs_requested(self):
        """View로부터 로그 초기화 요청을 받아 Model에 전달합니다."""
        self._model.archive_and_clear_logs()
