from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QTextEdit, QLabel
from valuator.utils.qt_studio.views.widgets.block_widget import BlockWidget
from valuator.utils.qt_studio.models.font_manager import FontManager


class FunctionTestView(QWidget):
    """선택된 함수를 테스트하는 뷰 (입력/실행/결과)"""

    def __init__(self, viewmodel, function, parent=None):
        super().__init__(parent)
        self._viewmodel = viewmodel
        self._function = function
        self._font_manager = FontManager.get_instance()

        layout = QVBoxLayout(self)

        # Input Section
        input_label = QLabel(f"Input for {function.__name__}:")
        self.input_area = QTextEdit()

        # ViewModel을 통해 예제 입력을 가져와 설정합니다.
        example_text = self._viewmodel.get_function_example(function.__name__)
        self.input_area.setText(example_text)

        self.input_area.setFixedHeight(150)

        # Execution Button
        self.run_button = QPushButton("Execute Function")

        # Output Section
        self.output_block = BlockWidget(
            "Result", "Execute the function to see the result."
        )

        layout.addWidget(input_label)
        layout.addWidget(self.input_area)
        layout.addWidget(self.run_button)
        layout.addWidget(self.output_block, stretch=1)

        # Connections
        self.run_button.clicked.connect(self.execute_function)
        self._viewmodel.function_execution_result.connect(self.update_result)

        # 폰트 크기 변경 시그널 연결
        self._font_manager.font_scale_changed.connect(self._update_fonts)

        # 초기 폰트 크기 적용
        self._update_fonts()

    def execute_function(self):
        input_text = self.input_area.toPlainText()
        self._viewmodel.execute_selected_function_async(input_text)

    def update_result(self, result_text):
        self.output_block.set_text(result_text)

    def _update_fonts(self):
        """폰트 크기를 업데이트합니다."""
        label_size = self._font_manager.get_font_size("label")
        text_size = self._font_manager.get_font_size("text")
        button_size = self._font_manager.get_font_size("button")

        # input_label 폰트 크기 업데이트
        for i in range(self.layout().count()):
            item = self.layout().itemAt(i)
            if item.widget():
                if isinstance(item.widget(), QLabel):
                    item.widget().setStyleSheet(f"font-size: {label_size}px;")
                elif isinstance(item.widget(), QTextEdit):
                    item.widget().setStyleSheet(f"font-size: {text_size}px;")
                elif isinstance(item.widget(), QPushButton):
                    item.widget().setStyleSheet(f"font-size: {button_size}px;")


class CentralView(QWidget):
    """중앙 메인 뷰어 (Sector B)"""

    def __init__(self, viewmodel, parent=None):
        super().__init__(parent)
        self._viewmodel = viewmodel

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Initial placeholder
        self.placeholder = QLabel("Select a function from the left sidebar to begin.")
        self.placeholder.setStyleSheet("font-size: 16px; color: #888;")
        self.layout.addWidget(self.placeholder)

        # Connections
        self._viewmodel.central_view_changed.connect(self.update_view)

    def update_view(self, function):
        # Clear current view
        while self.layout.count():
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add new function test view
        test_view = FunctionTestView(self._viewmodel, function)
        self.layout.addWidget(test_view)
