import os
import json
from datetime import datetime
from typing import Callable, List, Tuple

from PyQt5.QtCore import QObject, pyqtSignal
from google.cloud import firestore

from valuator.utils.qt_studio.models.font_manager import FontManager


LOG_FILE_PATH = "logs/qt_studio_logs.json"
LOG_SIZE_LIMIT = 1 * 1024 * 1024  # 1MB


def _ensure_log_directory_exists():
    """Ensures that the directory for logging exists."""
    log_dir = os.path.dirname(LOG_FILE_PATH)
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
            print(f"INFO: Created log directory at '{log_dir}'")
        except OSError as e:
            print(
                f"CRITICAL: Failed to create log directory at '{log_dir}'. Error: {e}"
            )


class AppState(QObject):
    """
    애플리케이션의 모든 상태를 관리하는 싱글턴 모델 클래스.
    - 등록된 함수 목록
    - 로그 메시지 목록
    상태 변경 시그널을 통해 ViewModel에 변경 사항을 알립니다.
    """

    _instance = None

    # Signals
    functions_changed = pyqtSignal()
    logs_changed = pyqtSignal()
    output_changed = pyqtSignal(str)  # 출력 변경 시그널

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        if AppState._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            _ensure_log_directory_exists()  # 앱 시작 시 디렉토리 생성 보장
            self.functions: List[Callable] = []
            self.utils: List[Callable] = []  # Placeholder for future
            self.logs: List[Tuple[str, str]] = []  # (level, message)
            self.function_examples: dict[str, str] = {}  # 예제 입력 저장
            self._output: str = ""  # 출력 저장 변수
            self.font_manager = FontManager.get_instance()  # 폰트 매니저 초기화
            AppState._instance = self
            self.load_logs_from_file()

    def add_function(self, func: Callable, example: str = ""):
        if func not in self.functions:
            self.functions.append(func)
            self.function_examples[func.__name__] = example
            self.functions_changed.emit()

    def add_log(
        self, level: str, message: str, title: str = None, timestamp: str = None
    ):
        self._check_and_rotate_log_file()
        # title 자동 생성 (기존 파싱 로직 활용)
        if title is None:
            import re

            func_name_match = re.search(r"'(.*?)'", message)
            func_name = func_name_match.group(1) if func_name_match else "System"
            title = f"[{level}] {func_name}"
            if len(title) > 50:
                title = title[:47] + "..."
        if timestamp is None:
            timestamp = datetime.now().isoformat(timespec="seconds")
        log_entry = {
            "level": level,
            "title": title,
            "message": message,
            "timestamp": timestamp,
        }
        self.logs.append(log_entry)
        self.logs_changed.emit()
        self.save_logs_to_file()

    def _check_and_rotate_log_file(self, forced: bool = False):
        """
        Checks log file size and rotates it if it exceeds the limit or if forced.
        """
        if not os.path.exists(LOG_FILE_PATH):
            return  # 아카이브할 파일이 없으면 즉시 종료

        try:
            # 강제 실행이 아니면 파일 크기를 체크
            should_archive = forced or (os.path.getsize(LOG_FILE_PATH) > LOG_SIZE_LIMIT)

            if should_archive:
                file_size = os.path.getsize(LOG_FILE_PATH)
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                base, ext = os.path.splitext(LOG_FILE_PATH)
                archive_path = f"{base}_{timestamp}.json"

                action = (
                    "Forced archiving"
                    if forced
                    else f"Archiving due to size ({file_size / (1024*1024):.2f}MB)"
                )
                print(f"INFO: {action}. Moving log to {archive_path}")

                os.rename(LOG_FILE_PATH, archive_path)

                # 아카이브 후에는 새 로그 파일을 위해 메모리를 비움
                self.logs = []
                self.logs_changed.emit()
            # else:
            #     # 아카이브 안 할 때는 메시지 없음 (너무 빈번한 출력 방지)

        except Exception as e:
            print(f"ERROR: Could not rotate log file. Error: {e}")

    def save_logs_to_file(self):
        """Saves the current log list to a JSON file."""
        self._check_and_rotate_log_file(forced=False)  # 일반 저장은 강제 안함
        try:
            with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.logs, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"CRITICAL: Failed to save logs to {LOG_FILE_PATH}. Error: {e}")

    def archive_and_clear_logs(self):
        """
        Archives the current logs if needed, then clears logs from memory and file.
        """
        # Debugging: "Clear and Save" action initiated. Print the target directory.
        log_dir = os.path.dirname(LOG_FILE_PATH)
        abs_log_dir = os.path.abspath(log_dir)
        print(f"DEBUG: 'Clear and Save' triggered. Archive location: {abs_log_dir}")

        # 1. Force archive the current log file.
        self._check_and_rotate_log_file(forced=True)

        # 2. Clear logs in memory (might have been cleared by rotate, but ensure it)
        self.logs = []
        print("INFO: All logs cleared from memory.")

        # 3. Save the now-empty state to the log file
        self.save_logs_to_file()

        # 4. Notify UI to update
        self.logs_changed.emit()

    def load_logs_from_file(self):
        """Loads logs from a JSON file if it exists. Handles migration from old format."""
        if os.path.exists(LOG_FILE_PATH):
            try:
                with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # 마이그레이션: 구버전([level, message]) → 신버전(dict)
                if loaded and isinstance(loaded[0], list):
                    migrated = []
                    for entry in loaded:
                        if len(entry) == 2:
                            level, message = entry
                            # title 생성 로직 재사용
                            import re

                            func_name_match = re.search(r"'(.*?)'", message)
                            func_name = (
                                func_name_match.group(1)
                                if func_name_match
                                else "System"
                            )
                            title = f"[{level}] {func_name}"
                            if len(title) > 50:
                                title = title[:47] + "..."
                            migrated.append(
                                {
                                    "level": level,
                                    "title": title,
                                    "message": message,
                                    "timestamp": None,
                                }
                            )
                        else:
                            migrated.append(
                                {
                                    "level": "INFO",
                                    "title": "[INFO] System",
                                    "message": str(entry),
                                    "timestamp": None,
                                }
                            )
                    self.logs = migrated
                else:
                    self.logs = loaded
                self.logs_changed.emit()
            except (json.JSONDecodeError, IOError) as e:
                print(f"WARNING: Could not load log file {LOG_FILE_PATH}. Error: {e}")
                self.logs = []
        else:
            self.logs = []

    def get_all_logs(self) -> list:
        return self.logs

    def get_all_functions(self) -> List[Callable]:
        return self.functions

    def get_function_example(self, func_name: str) -> str:
        """함수의 예제 입력을 반환합니다."""
        return self.function_examples.get(func_name, "")

    def set_output(self, output: str):
        """출력을 설정하고 시그널을 발생시킵니다."""
        self._output = output
        self.output_changed.emit(output)

    def get_output(self) -> str:
        """현재 출력을 반환합니다."""
        return self._output

    def upload_logs_to_firestore(self):
        """
        현재 로그를 Firestore에 업로드하고, 생성된 document id를 반환합니다.
        실패 시 예외를 발생시킵니다.
        """
        cred_path = os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json"
        )
        db = firestore.Client.from_service_account_json(cred_path)
        logs = self.get_all_logs()
        # 자동 document id 생성
        doc_ref = db.collection("log-v1").document()
        doc_ref.set({"content": logs})
        return doc_ref.id
