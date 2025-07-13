from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QLabel,
)
from functools import partial
from valuator.utils.qt_studio.models.font_manager import FontManager


class FunctionListView(QWidget):
    """함수 목록을 버튼으로 표시하는 스크롤 가능한 뷰"""

    def __init__(self, viewmodel, parent=None):
        super().__init__(parent)
        self._viewmodel = viewmodel
        self._font_manager = FontManager.get_instance()

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; }")

        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(0, 10, 0, 10)

        self.scroll_area.setWidget(self.container)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.scroll_area)

        # 폰트 크기 변경 시그널 연결
        self._font_manager.font_scale_changed.connect(self._update_button_fonts)

    def update_functions(self, functions):
        # Clear existing buttons
        while self.layout.count():
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add new buttons
        for func in functions:
            btn = QPushButton(func.__name__)
            btn.clicked.connect(partial(self._viewmodel.select_function, func))
            self.layout.addWidget(btn)

        self.layout.addStretch()

        # 초기 폰트 크기 적용
        self._update_button_fonts()

    def _update_button_fonts(self):
        """모든 버튼의 폰트 크기를 업데이트합니다."""
        button_size = self._font_manager.get_font_size("button")
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), QPushButton):
                item.widget().setStyleSheet(f"font-size: {button_size}px;")


class LeftSidebarView(QWidget):
    """좌측 사이드바 전체 (Sector A)"""

    def __init__(self, viewmodel, parent=None):
        super().__init__(parent)
        self._viewmodel = viewmodel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # --- Sector A1: Menu ---
        menu_layout = QHBoxLayout()
        self.func_button = QPushButton("Functions")
        self.utils_button = QPushButton("Utils")
        menu_layout.addWidget(self.func_button)
        menu_layout.addWidget(self.utils_button)
        layout.addLayout(menu_layout)

        # --- Sector A2: Stacked Viewer ---
        self.stacked_widget = QStackedWidget()
        self.func_view = FunctionListView(self._viewmodel)

        # Placeholder for utils view
        self.utils_view = QLabel("Utils List View (Placeholder)")
        self.utils_view.setWordWrap(True)

        self.stacked_widget.addWidget(self.func_view)
        self.stacked_widget.addWidget(self.utils_view)
        layout.addWidget(self.stacked_widget)

        # --- Connections ---
        self.func_button.clicked.connect(
            lambda: self.stacked_widget.setCurrentWidget(self.func_view)
        )
        self.utils_button.clicked.connect(
            lambda: self.stacked_widget.setCurrentWidget(self.utils_view)
        )
        self._viewmodel.function_list_updated.connect(self.func_view.update_functions)

        # Initial state
        self.stacked_widget.setCurrentWidget(self.func_view)
