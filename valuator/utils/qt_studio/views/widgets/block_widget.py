from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QApplication, QSizePolicy, QWidget, QMainWindow, QComboBox
from PyQt5.QtCore import pyqtSignal
from valuator.utils.qt_studio.models.font_manager import FontManager
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
        self._current_render_mode = "raw"  # 현재 렌더링 모드
        self.extra_windows = [] # 열린 새 창들의 참조를 저장할 리스트
        self._font_manager = FontManager.get_instance()
        
        self.setFrameShape(QFrame.StyledPanel)
        self._update_stylesheet()
        
        # 폰트 크기 변경 시그널 연결
        self._font_manager.font_scale_changed.connect(self._update_stylesheet)

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
        self._update_title_style(title_color)
        
        title_row.addWidget(self.title_label)
        # title_row.addStretch() # 이 라인을 제거하여 제목이 남는 공간을 채우도록 함

        # Buttons
        self.new_window_btn = QPushButton("Open")
        self.copy_btn = QPushButton("Copy")
        
        # 렌더링 모드 드롭다운 메뉴
        self.render_combo = QComboBox()
        self.render_combo.addItems(["Raw Text", "Monospace", "Markdown", "JSON"])
        self.render_combo.setCurrentText("Raw Text")
        self.render_combo.currentTextChanged.connect(self._on_render_mode_changed)

        # 버튼들이 텍스트 크기에 맞게 조절되도록 크기 정책 설정
        for btn in [self.new_window_btn, self.copy_btn]:
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.render_combo.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        title_row.addWidget(self.new_window_btn)
        title_row.addWidget(self.copy_btn)
        title_row.addWidget(self.render_combo)
        
        layout.addLayout(title_row)

        # Text area
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self._raw_text)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        # Connect internal signals
        self.copy_btn.clicked.connect(self._on_copy)
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

    def _on_render_mode_changed(self, mode: str):
        """렌더링 모드가 변경되었을 때 호출됩니다."""
        self._current_render_mode = mode.lower().replace(" ", "_")
        self._render_content()

    def _render_content(self):
        """현재 선택된 모드에 따라 콘텐츠를 렌더링합니다."""
        if getattr(self, 'title_label', None) and self.title_label.text().upper().startswith('[ERROR]'):
            # [ERROR]로 시작하면 monospace
            self._update_error_text_style()
            self.text_edit.setPlainText(self._raw_text)
            return

        # 정상 결과는 시스템 기본 폰트
        self._update_normal_text_style()
        
        if self._current_render_mode == "markdown":
            html = markdown.markdown(self._raw_text, extensions=['tables'])
            html = DARK_MODE_TABLE_STYLE + html
            self.text_edit.setHtml(html)
        elif self._current_render_mode == "json":
            try:
                import json
                import re
                
                # JSON 전처리: single quote를 double quote로 변환
                preprocessed_text = self._preprocess_json_text(self._raw_text)
                
                parsed_json = json.loads(preprocessed_text)
                formatted_json = json.dumps(parsed_json, indent=2, ensure_ascii=False, sort_keys=True)
                
                # JSON beautify를 위한 HTML 스타일 적용
                self._update_json_text_style()
                
                # 단순히 포맷팅된 JSON을 표시 (색상 강조 없음)
                self.text_edit.setPlainText(formatted_json)
                
            except Exception as e:
                # JSON 파싱 실패 시 원본 텍스트 표시
                self.text_edit.setPlainText(self._raw_text)
        elif self._current_render_mode == "monospace":
            # Monospace 모드에서는 고정폭 폰트 사용
            self._update_monospace_text_style()
            self.text_edit.setPlainText(self._raw_text)
        else:  # raw_text
            self.text_edit.setPlainText(self._raw_text)

    def set_text(self, text: str):
        """외부에서 위젯의 텍스트를 설정합니다. 렌더링 상태를 유지합니다."""
        self._raw_text = text
        self._render_content()

    def _update_stylesheet(self):
        """현재 폰트 크기에 맞게 스타일시트를 업데이트합니다."""
        label_size = self._font_manager.get_font_size("label")
        text_size = self._font_manager.get_font_size("text")
        button_size = self._font_manager.get_font_size("button")
        
        stylesheet = f"""
            QFrame {{ /* The main widget's frame */
                background-color: #2E2E2E;
                border: 1px solid #454545;
                border-radius: 8px;
            }}
            QLabel {{
                color: #EAEAEA;
                font-weight: bold; 
                font-size: {label_size}px;
                padding-left: 5px; /* Add some padding */
            }}
            QTextEdit {{
                background-color: #252525;
                color: #D3D3D3;
                border-radius: 4px;
                border: 1px solid #454545;
                font-size: {text_size}px;
                padding: 8px;
                font-family: 'Segoe UI', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Arial', 'sans-serif';
            }}
            QPushButton {{
                background-color: #4A4A4A;
                color: #EAEAEA;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                font-size: {button_size}px;
            }}
            QPushButton:hover {{
                background-color: #5A5A5A;
            }}
            QPushButton:pressed {{
                background-color: #6A6A6A;
            }}
            QComboBox {{
                background-color: #4A4A4A;
                color: #EAEAEA;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                font-size: {button_size}px;
                min-width: 100px;
            }}
            QComboBox:hover {{
                background-color: #5A5A5A;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #EAEAEA;
                margin-right: 5px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #4A4A4A;
                color: #EAEAEA;
                border: 1px solid #5A5A5A;
                selection-background-color: #5A5A5A;
            }}
        """
        self.setStyleSheet(stylesheet)
    
    def _update_title_style(self, color: str):
        """제목 라벨의 스타일을 업데이트합니다."""
        title_size = self._font_manager.get_font_size("title")
        self.title_label.setStyleSheet(f"font-weight: bold; font-size: {title_size}px; color: {color};")
    
    def _update_normal_text_style(self):
        """일반 텍스트 스타일을 업데이트합니다."""
        text_size = self._font_manager.get_font_size("text")
        self.text_edit.setStyleSheet(f"""
            background-color: #252525;
            color: #D3D3D3;
            border-radius: 4px;
            border: 1px solid #454545;
            font-size: {text_size}px;
            padding: 8px;
        """)
    
    def _update_error_text_style(self):
        """에러 텍스트 스타일을 업데이트합니다."""
        text_size = self._font_manager.get_font_size("text")
        self.text_edit.setStyleSheet(f"""
            background-color: #252525;
            color: #D3D3D3;
            border-radius: 4px;
            border: 1px solid #454545;
            font-size: {text_size}px;
            padding: 8px;
            font-family: 'D2Coding', 'Consolas', 'Menlo', 'Monaco', 'monospace';
        """)
    
    def _update_monospace_text_style(self):
        """Monospace 텍스트 스타일을 업데이트합니다."""
        text_size = self._font_manager.get_font_size("text")
        self.text_edit.setStyleSheet(f"""
            background-color: #252525;
            color: #D3D3D3;
            border-radius: 4px;
            border: 1px solid #454545;
            font-size: {text_size}px;
            padding: 8px;
            font-family: 'D2Coding', 'Consolas', 'Menlo', 'Monaco', 'monospace';
        """)
    
    def _update_json_text_style(self):
        """JSON 텍스트 스타일을 업데이트합니다."""
        text_size = self._font_manager.get_font_size("text")
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: #1E1E1E;
                color: #D4D4D4;
                border-radius: 4px;
                border: 1px solid #454545;
                font-size: {text_size}px;
                padding: 8px;
                font-family: 'D2Coding', 'Consolas', 'Menlo', 'Monaco', 'monospace';
                line-height: 1.4;
            }}
        """)
    
    def _preprocess_json_text(self, text: str) -> str:
        """JSON 파싱을 위해 텍스트를 전처리합니다."""
        import re
        
        # 1. 문자열 내의 single quote를 double quote로 변환
        # 단, 이미 올바른 JSON 문자열 내부의 double quote는 건드리지 않음
        processed = text
        
        # 2. 문자열 패턴을 찾아서 내부의 single quote를 double quote로 변환
        # 문자열은 따옴표로 둘러싸인 부분을 의미
        def replace_single_quotes_in_strings(match):
            content = match.group(1)
            # 문자열 내부의 single quote를 double quote로 변환
            content = content.replace("'", '"')
            return f'"{content}"'
        
        # single quote로 둘러싸인 문자열을 찾아서 변환
        processed = re.sub(r"'([^']*)'", replace_single_quotes_in_strings, processed)
        
        # 3. 키 이름에서 single quote를 double quote로 변환
        # 키는 콜론 앞에 있는 부분
        def replace_single_quotes_in_keys(match):
            key = match.group(1)
            key = key.replace("'", '"')
            return f'"{key}":'
        
        processed = re.sub(r"'([^']*)':", replace_single_quotes_in_keys, processed)
        
        # 4. 불린 값 변환 (Python 스타일 -> JSON 스타일)
        processed = re.sub(r'\bTrue\b', 'true', processed)
        processed = re.sub(r'\bFalse\b', 'false', processed)
        processed = re.sub(r'\bNone\b', 'null', processed)
        
        return processed
    


class FullTextBlockWidget(BlockWidget):
    def __init__(self, title: str, text: str, level: str = "INFO", parent=None):
        super().__init__(title, text, level, parent)
        self.new_window_btn.setDisabled(True)
