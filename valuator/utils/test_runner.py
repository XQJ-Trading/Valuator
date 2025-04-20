import sys
import random
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTextEdit, QTextBrowser, QAbstractScrollArea, QPushButton,
    QScrollArea, QFrame, QLabel, QHBoxLayout, 
)
from PyQt6.QtCore import Qt, QTimer
from qasync import QEventLoop
from typing import Callable
import time

# Dummy lorem ipsum texts for placeholder
DUMMY_TEXTS = [
    "# Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vivamus lacinia odio vitae vestibulum vestibulum.",
    "## Cras placerat ultricies sapien, et malesuada turpis hendrerit nec. Nullam vehicula.",
    "Phasellus venenatis elit eu augue luctus, ut varius massa fermentum."
]

class BlockWidget(QFrame):
    def __init__(self, title: str, text: str):
        super().__init__()
        # Style: simple rounded rectangle
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid #ccc; border-radius: 8px; padding: 8px; margin: 4px; }"
        )

        layout = QVBoxLayout(self)
        # Title label
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label)

        # Text area (Markdown-rendered)
        text_browser = QTextBrowser()
        text_browser.setReadOnly(True)
        # Remove size adjust policy
        # text_browser.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            text_browser.setMarkdown(text)
        except AttributeError:
            text_browser.setPlainText(text)
        # Auto-adjust height to content (run after setting text)
        layout.addWidget(text_browser)
        # Delay size adjustment until widget is laid out
        def _update_size():
            text_browser.document().setTextWidth(text_browser.viewport().width())
            doc_height = text_browser.document().size().height()
            text_browser.setFixedHeight(int(doc_height + text_browser.frameWidth() * 2))
        QTimer.singleShot(0, _update_size)

class ChatWindow(QWidget):
    def __init__(self, generator: Callable[[list[str]], str]):
        super().__init__()
        self.generator = generator
        self.setWindowTitle("PyQt6 Chat Example")
        self.resize(800, 600)

        # Main vertical layout: input area (1/3) on top, chat area (2/3) at bottom
        main_layout = QVBoxLayout(self)

        # Input area
        input_area = QWidget()
        input_layout = QVBoxLayout(input_area)
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("Type your message here...")
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
        response_text = self.generator(text)

        # Add the response block
        title = self.generator.__name__
        answer_block = BlockWidget(title, response_text)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, answer_block)
        self.input_edit.clear()

def run(generator: Callable[[list[str]], str]) -> None:
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    window = ChatWindow(generator)
    window.show()
    with loop:
        loop.run_forever()

if __name__ == '__main__':

    # Example generator: sleeps then returns lorem ipsum.
    def dummy_generator(_: str) -> str:
        return '\n\n'.join([random.choice(DUMMY_TEXTS) for _ in range(100)])
    
    run(dummy_generator)
