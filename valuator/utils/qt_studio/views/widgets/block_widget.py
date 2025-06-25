from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QApplication, QSizePolicy, QWidget, QMainWindow
from PyQt5.QtCore import pyqtSignal
import markdown

# "Open" 버튼 클릭 시 전체 텍스트를 보여주는 새 창 클래스
class TextWindow(QWidget):
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(100, 100, 800, 600) # 창 위치와 크기 설정

        layout = QVBoxLayout(self)
        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        text_edit.setReadOnly(True)
        # BlockWidget과 유사한 스타일 적용
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #252525;
                color: #D3D3D3;
                border: none;
                font-size: 14px;
                padding: 8px;
            }
        """)
        layout.addWidget(text_edit)
        self.setLayout(layout)

DARK_MODE_TABLE_STYLE = '''<style>
table {
  border-collapse: collapse;
  width: 100%;
  background: #23272e;
  border-radius: 8px;
  overflow: hidden;
  margin: 8px 0;
}
th, td {
  border: 1px solid #3a3f4b;
  padding: 8px 12px;
  text-align: left;
  color: #e0e6ed;
}
th {
  background: #2d3440;
  color: #7ec7ff;
  font-weight: bold;
}
tr:nth-child(even) {
  background: #262b33;
}
tr:nth-child(odd) {
  background: #23272e;
}
</style>'''

class BlockWidget(QFrame):
    """
    제목, 텍스트 상자, 버튼을 포함하는 재사용 가능한 위젯.
    """
    # 이 위젯 자체의 버튼 클릭 시그널 (필요 시 외부에서 사용)
    copy_clicked = pyqtSignal()
    open_in_new_window_clicked = pyqtSignal()

    def __init__(self, title: str, text: str, level: str = "INFO", parent=None):
        super().__init__(parent)
        self._raw_text = text  # 원본 텍스트 저장
        self._is_md_rendered = False
        self.extra_windows = [] # 열린 새 창들의 참조를 저장할 리스트
        
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame { /* The main widget's frame */
                background-color: #2E2E2E;
                border: 1px solid #454545;
                border-radius: 8px;
            }
            QLabel {
                color: #EAEAEA;
                font-weight: bold; 
                font-size: 14px;
                padding-left: 5px; /* Add some padding */
            }
            QTextEdit {
                background-color: #252525;
                color: #D3D3D3;
                border-radius: 4px;
                border: 1px solid #454545;
                font-size: 13px;
                padding: 8px;
                font-family: 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Arial', 'sans-serif';
            }
            QPushButton {
                background-color: #4A4A4A;
                color: #EAEAEA;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5A5A5A;
            }
            QPushButton:pressed {
                background-color: #6A6A6A;
            }
        """)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        # Title and button row
        title_row = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        
        # 레벨에 따라 제목 색상 동적 변경
        if level == "ERROR":
            title_color = "#E57373" # Soft Red
        elif level == "SUCCESS":
            title_color = "#81C784" # Soft Green
        else:
            title_color = "#EAEAEA" # Default
        self.title_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {title_color};")
        
        title_row.addWidget(self.title_label)
        # title_row.addStretch() # 이 라인을 제거하여 제목이 남는 공간을 채우도록 함

        # Buttons
        self.new_window_btn = QPushButton("Open")
        self.copy_btn = QPushButton("Copy")
        self.md_button = QPushButton("Render as MD")

        # 버튼들이 텍스트 크기에 맞게 조절되도록 크기 정책 설정
        for btn in [self.new_window_btn, self.copy_btn, self.md_button]:
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        title_row.addWidget(self.new_window_btn)
        title_row.addWidget(self.copy_btn)
        title_row.addWidget(self.md_button)
        
        layout.addLayout(title_row)

        # Text area
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self._raw_text)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        # Connect internal signals
        self.copy_btn.clicked.connect(self._on_copy)
        self.md_button.clicked.connect(self.toggle_md_render)
        self.new_window_btn.clicked.connect(self._open_in_new_window) # Open 버튼 연결

    def _on_copy(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self._raw_text)
        self.copy_clicked.emit()

    def _open_in_new_window(self):
        """전체 텍스트 내용을 새 창에서 BlockWidget 스타일로 엽니다."""
        from PyQt5.QtWidgets import QMainWindow
        class FullTextWindow(QMainWindow):
            def __init__(self, title, text, level):
                super().__init__()
                self.setWindowTitle(title)
                self.setGeometry(100, 100, 900, 700)
                widget = FullTextBlockWidget(title, text, level)
                self.setCentralWidget(widget)
        new_window = FullTextWindow(f"Full View: {self.title_label.text()}", self._raw_text, self.title_label.text())
        new_window.destroyed.connect(lambda: self.extra_windows.remove(new_window))
        self.extra_windows.append(new_window)
        new_window.show()

    def set_text(self, text: str):
        """외부에서 위젯의 텍스트를 설정합니다. 렌더링 상태를 유지합니다."""
        self._raw_text = text
        if getattr(self, 'title_label', None) and self.title_label.text().upper().startswith('[ERROR]'):
            # [ERROR]로 시작하면 monospace
            self.text_edit.setStyleSheet("""
                background-color: #252525;
                color: #D3D3D3;
                border-radius: 4px;
                border: 1px solid #454545;
                font-size: 13px;
                padding: 8px;
                font-family: 'D2Coding', 'Consolas', 'Menlo', 'Monaco', 'monospace';
            """)
            self.text_edit.setPlainText(self._raw_text)
            return
        # 정상 결과는 시스템 기본 폰트
        self.text_edit.setStyleSheet("""
            background-color: #252525;
            color: #D3D3D3;
            border-radius: 4px;
            border: 1px solid #454545;
            font-size: 13px;
            padding: 8px;
        """)
        if self._is_md_rendered:
            html = markdown.markdown(self._raw_text, extensions=['tables'])
            html = DARK_MODE_TABLE_STYLE + html
            self.text_edit.setHtml(html)
        else:
            self.text_edit.setPlainText(self._raw_text)

    def toggle_md_render(self):
        """마크다운 렌더링 상태를 토글합니다."""
        self._is_md_rendered = not self._is_md_rendered
        
        if self._is_md_rendered:
            # 현재 표시된 텍스트가 원본이라고 가정하고 렌더링
            self._raw_text = self.text_edit.toPlainText()
            html = markdown.markdown(self._raw_text, extensions=['tables'])
            html = DARK_MODE_TABLE_STYLE + html
            self.text_edit.setHtml(html)
            self.md_button.setText("Show Raw")
        else:
            # 저장된 원본 텍스트로 복원
            self.text_edit.setPlainText(self._raw_text)
            self.md_button.setText("Render as MD")

class FullTextBlockWidget(BlockWidget):
    def __init__(self, title: str, text: str, level: str = "INFO", parent=None):
        super().__init__(title, text, level, parent)
        self.new_window_btn.setDisabled(True)
