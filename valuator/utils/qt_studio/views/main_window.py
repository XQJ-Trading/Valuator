from PyQt5.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QSplitter, QApplication
from PyQt5.QtCore import Qt
from valuator.utils.qt_studio.views.left_sidebar import LeftSidebarView
from valuator.utils.qt_studio.views.right_sidebar import RightSidebarView
from valuator.utils.qt_studio.views.central_viewer import CentralView

class MainWindow(QMainWindow):
    """
    애플리케이션의 메인 윈도우.
    세 개의 섹터(A, B, C) 레이아웃을 구성하고 각 뷰를 배치합니다.
    """
    def __init__(self, viewmodel):
        super().__init__()
        self._viewmodel = viewmodel
        self.setWindowTitle("QT Studio")
        self.setGeometry(100, 100, 1600, 900)

        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # Create splitter for resizable sections
        splitter = QSplitter(Qt.Horizontal)

        # Instantiate views
        self.left_sidebar = LeftSidebarView(self._viewmodel)
        self.central_view = CentralView(self._viewmodel)
        self.right_sidebar = RightSidebarView(self._viewmodel)

        # Add views to splitter
        splitter.addWidget(self.left_sidebar)
        splitter.addWidget(self.central_view)
        splitter.addWidget(self.right_sidebar)

        # Set initial sizes for the sections
        splitter.setSizes([200, 800, 600])
        
        main_layout.addWidget(splitter)

    # keyPressEvent 메서드를 오버라이드하여 단축키 처리
    def keyPressEvent(self, event):
        """ 키보드 이벤트를 직접 처리하여 한/영 상태와 무관하게 단축키를 감지합니다. """
        if event.key() == Qt.Key_W and event.modifiers() == Qt.ControlModifier:
            QApplication.instance().quit()
        else:
            super().keyPressEvent(event)
