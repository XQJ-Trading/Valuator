import sys
import json

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QScrollArea,
    QFrame,
    QLabel,
    QHBoxLayout,
)
from PyQt5.QtCore import Qt
from typing import Callable


class BlockWidget(QFrame):
    def __init__(self, title: str, text: str):
        super().__init__()
        # Style: simple rounded rectangle
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid #ccc; border-radius: 8px; padding: 8px; margin: 4px; }"
        )

        layout = QVBoxLayout(self)
        # Title label
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label)

        # Text area (Markdown-rendered)
        text_edit = QTextEdit()
        text_edit.setFocusPolicy(Qt.StrongFocus)
        text_edit.setTextInteractionFlags(Qt.TextEditorInteraction)
        # Load content
        try:
            text_edit.setMarkdown(text)
        except AttributeError:
            text_edit.setPlainText(text)
        # Resize to content if desired
        layout.addWidget(text_edit)


class ChatWindow(QWidget):
    def __init__(self, generator: Callable[[list[str]], str]):
        super().__init__()
        self.generator = generator
        self.setWindowTitle(f"test {generator.__name__}")
        self.resize(800, 600)

        # Main vertical layout: input area (1/3) on top, chat area (2/3) at bottom
        main_layout = QVBoxLayout(self)

        # Input area
        input_area = QWidget()
        input_layout = QVBoxLayout(input_area)
        self.input_edit = QTextEdit()
        # self.input_edit.setPlaceholderText('example: {"corp": "Black Lab"}')
        self.input_edit.setText('{"corp": "Black Lab"}')
        submit_btn = QPushButton("Submit")
        submit_btn.setFixedWidth(80)
        submit_btn.clicked.connect(self.add_message)
        # Align button to the right
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(submit_btn)

        input_layout.addWidget(self.input_edit)
        input_layout.addLayout(btn_layout)

        # Chat area with scroll
        self.chat_area = QScrollArea()
        self.chat_area.setWidgetResizable(True)
        chat_container = QWidget()
        self.chat_layout = QVBoxLayout(chat_container)
        self.chat_layout.addStretch()
        self.chat_area.setWidget(chat_container)

        # Add sections to main layout with stretch factors (1:2)
        main_layout.addWidget(input_area, stretch=1)
        main_layout.addWidget(self.chat_area, stretch=2)

    def add_message(self):
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        # Add a block for the user's question
        user_block = BlockWidget("You", text)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, user_block)

        # Call generator (may sleep)
        data = json.loads(text)
        response_text = json.dumps(self.generator(data))

        # Add the response block
        title = self.generator.__name__
        answer_block = BlockWidget(title, response_text)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, answer_block)
        self.input_edit.clear()


list_of_methods = []


def append_to_methods(func):
    list_of_methods.append(func)
    return func


def run_runners():
    app = QApplication(sys.argv)
    windows = []
    sel_window = QWidget()
    sel_window.setWindowTitle("Select Runner")
    layout = QVBoxLayout(sel_window)
    for func in list_of_methods:
        btn = QPushButton(func.__name__)

        def handler(checked, f=func, windows=windows):
            print(f)
            cw = ChatWindow(f)
            windows.append(cw)
            cw.show()

        btn.clicked.connect(handler)
        layout.addWidget(btn)
    sel_window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    pass
