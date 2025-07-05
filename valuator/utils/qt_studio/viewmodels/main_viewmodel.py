from PyQt5.QtCore import QObject, pyqtSignal, QThread
from valuator.utils.qt_studio.models.app_state import AppState
import traceback
import inspect

class FunctionRunner(QThread):
    log_signal = pyqtSignal(str, str)  # (level, message)
    result_signal = pyqtSignal(object) # 최종 결과
    error_signal = pyqtSignal(str)     # 에러 메시지

    def __init__(self, func, args=(), kwargs=None, parent=None):
        super().__init__(parent)
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self._is_running = True

    def run(self):
        try:
            # 함수 실행 중간에 로그를 남기고 싶으면, 로그 콜백을 kwargs로 전달
            def log_callback(level, msg):
                self.log_signal.emit(level, msg)

            # 함수가 log_callback 파라미터를 받을 수 있는지 확인
            sig = inspect.signature(self.func)
            if 'log_callback' in sig.parameters:
                self.kwargs['log_callback'] = log_callback

            result = self.func(*self.args, **self.kwargs)
            self.result_signal.emit(result)
        except Exception as e:
            tb = traceback.format_exc()
            self.error_signal.emit(tb)

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
        self._model.output_changed.connect(self.function_execution_result.emit)  # 출력 변경 시그널 연결

    def load_initial_data(self):
        """ 초기 데이터 로드를 트리거합니다. """
        self.update_function_list()
        self.update_log_list()
        self._model.add_log(
            level="INFO",
            message="Application started.",
            title="[INFO] Application started"
        )

    def update_function_list(self):
        functions = self._model.get_all_functions()
        self.function_list_updated.emit(functions)

    def update_log_list(self):
        logs = self._model.get_all_logs()
        log_count = len(logs)
        print(f"DEBUG: ViewModel: log_list_updated signal emitted with {log_count} logs.")
        self.log_list_updated.emit(logs)

    def select_function(self, func):
        """ 사용자가 function list에서 함수를 선택했을 때 호출됩니다. """
        self._selected_function = func
        self._model.add_log(
            level="INFO",
            message=f"Function '{func.__name__}' selected.",
            title=f"[INFO] Function Selected"
        )
        # 중앙 뷰어 변경 시그널을 보냅니다. (실제 View는 main_window에서 생성)
        self.central_view_changed.emit(func)

    def execute_selected_function(self, input_text: str):
        """ 선택된 함수를 실행합니다. """
        if not self._selected_function:
            self._model.add_log(
                level="ERROR",
                message="No function selected to execute.",
                title="[ERROR] Function Execution"
            )
            return

        func_name = self._selected_function.__name__
        
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

    def execute_function_async(self, func, *args, **kwargs):
        """
        주어진 함수를 별도의 QThread(FunctionRunner)에서 비동기로 실행.
        실행 중에는 output에 '실행중...'을 표시하고, 중간 로그/최종 결과/에러를 각각 시그널로 받아 처리.
        로그 기록 시 재정의된 API 형식(level, message, title)을 반드시 사용.
        """
        self._model.set_output("실행중...")
        self._runner = FunctionRunner(func, args, kwargs)
        # 로그 시그널 연결: level, message를 받아 title을 포함하여 기록
        self._runner.log_signal.connect(
            lambda level, msg: self._model.add_log(
                level=level,
                message=msg,
                title=f"[{level}] FunctionRunner Log"
            )
        )
        self._runner.result_signal.connect(self._on_function_result)
        self._runner.error_signal.connect(
            lambda tb: self._model.add_log(
                level="ERROR",
                message=f"FunctionRunner Error: {tb}",
                title="[ERROR] FunctionRunner"
            ) or self._on_function_error(tb)
        )
        self._runner.start()

    def _on_function_result(self, result):
        self._model.set_output(str(result))
        self._runner = None

    def _on_function_error(self, tb):
        self._model.set_output(f"ERROR\n{tb}")
        self._runner = None

    def execute_selected_function_async(self, input_text: str):
        """
        선택된 함수를 비동기로 실행합니다.
        """
        if not self._selected_function:
            self._model.add_log(
                level="ERROR",
                message="No function selected to execute.",
                title="[ERROR] Function Execution"
            )
            return
        func = self._selected_function
        self.execute_function_async(func, input_text)
