from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QLabel,
)
from PyQt5.QtCore import QTimer, Qt
from valuator.utils.qt_studio.views.widgets.block_widget import BlockWidget
from typing import List, Tuple
import re  # 정규표현식 모듈 임포트


class LogListView(QWidget):
    """로그 목록을 표시하는 스크롤 가능한 뷰"""

    def __init__(self, viewmodel, parent=None):
        super().__init__(parent)
        self._viewmodel = viewmodel

        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; }")
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.addStretch()
        self.scroll_area.setWidget(self.container)
        main_layout.addWidget(self.scroll_area)

        # Button Area
        button_layout = QHBoxLayout()
        self.clear_button = QPushButton("Clear and Save")
        self.upload_button = QPushButton("Upload")
        button_layout.addStretch()  # 버튼을 오른쪽으로 정렬
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.upload_button)
        main_layout.addLayout(button_layout)

        # Connections
        self.clear_button.clicked.connect(self._viewmodel.clear_logs_requested)
        self.upload_button.clicked.connect(self._viewmodel.upload_logs_requested)
        if hasattr(self._viewmodel, "upload_finished"):
            self._viewmodel.upload_finished.connect(self.show_upload_result)

    def update_logs(self, logs):
        print(f"[DEBUG] View: Received {len(logs)} logs to display.")
        # Clear existing logs except the last stretch
        for i in reversed(range(self.layout.count())):
            item = self.layout.itemAt(i)
            widget = item.widget() if item else None
            if widget and not isinstance(widget, QLabel):  # stretch는 widget이 None
                widget.setParent(None)
            elif widget is None and i != self.layout.count() - 1:
                # stretch가 마지막이 아니면 제거
                self.layout.takeAt(i)

        # Add new logs (dict 기반)
        for log in logs:
            title = log.get("title", "[INFO] System")
            message = log.get("message", "")
            level = log.get("level", "INFO")
            block = BlockWidget(title, message, level=level)
            self.layout.insertWidget(self.layout.count() - 1, block)

        # stretch가 마지막에 없으면 추가
        if (
            self.layout.count() == 0
            or self.layout.itemAt(self.layout.count() - 1).widget() is not None
        ):
            self.layout.addStretch()

        # 로그 추가 후 스크롤을 맨 아래로
        QTimer.singleShot(
            100,
            lambda: self.scroll_area.verticalScrollBar().setValue(
                self.scroll_area.verticalScrollBar().maximum()
            ),
        )

    def show_upload_result(self, doc_id):
        from PyQt5.QtWidgets import QMessageBox

        url = f"https://qt-studio-log-viewer.vercel.app/{doc_id}"
        QMessageBox.information(
            self,
            "업로드 완료",
            f"업로드가 완료되었습니다!\n\n아래 링크를 복사해 사용하세요:\n{url}",
        )


class RightSidebarView(QWidget):
    """우측 사이드바 전체 (Sector C)"""

    def __init__(self, viewmodel, parent=None):
        super().__init__(parent)
        self._viewmodel = viewmodel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # --- Sector C1: Menu ---
        menu_layout = QHBoxLayout()
        self.log_button = QPushButton("Logs")
        self.cache_button = QPushButton("Cache")
        menu_layout.addWidget(self.log_button)
        menu_layout.addWidget(self.cache_button)
        layout.addLayout(menu_layout)

        # --- Sector C2: Stacked Viewer ---
        self.stacked_widget = QStackedWidget()
        self.log_view = LogListView(self._viewmodel)

        # Placeholder for cache view
        self.cache_view_placeholder = QLabel("Cache View (Not Implemented)")
        self.cache_view_placeholder.setWordWrap(True)

        self.stacked_widget.addWidget(self.log_view)
        self.stacked_widget.addWidget(self.cache_view_placeholder)
        layout.addWidget(self.stacked_widget)

        # --- Connections ---
        self.log_button.clicked.connect(
            lambda: self.stacked_widget.setCurrentWidget(self.log_view)
        )
        self.cache_button.clicked.connect(
            lambda: self.stacked_widget.setCurrentWidget(self.cache_view_placeholder)
        )
        self._viewmodel.log_list_updated.connect(self.log_view.update_logs)

        # Initial state
        self.stacked_widget.setCurrentWidget(self.log_view)
