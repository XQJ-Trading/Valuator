import sys
from PyQt5.QtWidgets import QApplication

from valuator.utils.qt_studio.models.app_state import AppState
from valuator.utils.qt_studio.viewmodels.main_viewmodel import MainViewModel
from valuator.utils.qt_studio.views.main_window import MainWindow


def start_app():
    """
    애플리케이션을 초기화하고 실행합니다.
    """
    app = QApplication(sys.argv)

    # 1. Model 생성
    app_state = AppState.get_instance()

    # 2. ViewModel 생성 및 Model 연결
    view_model = MainViewModel(app_state)

    # 3. View 생성 및 ViewModel 연결
    main_view = MainWindow(view_model)

    # 4. 초기 데이터 로드
    view_model.load_initial_data()

    # 5. 애플리케이션 실행
    main_view.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    start_app()
