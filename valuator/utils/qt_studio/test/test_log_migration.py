import os
import json
import tempfile
from valuator.utils.qt_studio.models.app_state import AppState, LOG_FILE_PATH


def test_log_migration():
    # 1. 구버전 로그 파일 생성
    old_logs = [
        ["INFO", "Executing 'foo' with args: (1,), kwargs: {}"],
        ["ERROR", "Error in 'bar': something went wrong"],
        ["SUCCESS", "'baz' completed successfully"],
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "qt_studio_logs.json")
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(old_logs, f)
        # 2. AppState가 해당 파일을 읽도록 경로를 임시로 바꾼다
        orig_path = AppState.__dict__["__init__"].__globals__["LOG_FILE_PATH"]
        AppState.__dict__["__init__"].__globals__["LOG_FILE_PATH"] = log_path
        try:
            # 3. AppState 인스턴스 생성 및 마이그레이션
            if AppState._instance:
                AppState._instance = None  # 싱글턴 초기화
            app_state = AppState.get_instance()
            logs = app_state.get_all_logs()
            assert isinstance(logs, list)
            assert isinstance(logs[0], dict)
            assert "title" in logs[0]
            assert logs[0]["title"].startswith("[INFO]")
            print("Migration test passed. Migrated logs:")
            for log in logs:
                print(log)
        finally:
            # 경로 복원
            AppState.__dict__["__init__"].__globals__["LOG_FILE_PATH"] = orig_path
            AppState._instance = None


if __name__ == "__main__":
    test_log_migration()
