from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QScrollArea, QStackedWidget, QLabel
from PyQt5.QtCore import QTimer, Qt
from valuator.utils.qt_studio.views.widgets.block_widget import BlockWidget
from typing import List, Tuple
import re # 정규표현식 모듈 임포트

class LogListView(QWidget):
    """ 로그 목록을 표시하는 스크롤 가능한 뷰 """
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
        button_layout.addStretch() # 버튼을 오른쪽으로 정렬
        button_layout.addWidget(self.clear_button)
        main_layout.addLayout(button_layout)

        # Connections
        self.clear_button.clicked.connect(self._viewmodel.clear_logs_requested)

    def update_logs(self, logs: List[Tuple[str, str]]):
        print(f"[DEBUG] View: Received {len(logs)} logs to display.")
        # Clear existing logs
        for i in reversed(range(self.layout.count() - 1)):
            widget = self.layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Add new logs
        for level, message in logs:
            # 메시지에서 함수명 파싱
            func_name_match = re.search(r"'(.*?)'", message)
            func_name = func_name_match.group(1) if func_name_match else "System"
            
            # 새로운 제목 생성
            title = f"[{level}] {func_name}"
            
            # 제목을 50자로 제한
            if len(title) > 50:
                title = title[:47] + "..."

            # BlockWidget 생성 시 level 전달
            block = BlockWidget(title, message, level=level)
            self.layout.insertWidget(self.layout.count() - 1, block)
        
        # QTimer.singleShot을 사용하여 UI 갱신 후 스크롤을 내립니다.
        QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum()))

class RightSidebarView(QWidget):
    """ 우측 사이드바 전체 (Sector C) """
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
        self.log_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.log_view))
        self.cache_button.clicked.connect(lambda: self.stacked_widget.setCurrentWidget(self.cache_view_placeholder))
        self._viewmodel.log_list_updated.connect(self.log_view.update_logs)

        # Initial state
        self.stacked_widget.setCurrentWidget(self.log_view)
