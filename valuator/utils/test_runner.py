import sys
import traceback

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
    QShortcut,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence, QClipboard
from typing import Callable, List

from valuator.utils.llm_utils import translate


class TextWindow(QWidget):
    def __init__(self, title: str, text: str, windows: List["TextWindow"]):
        super().__init__()
        self.windows = windows
        self.windows.append(self)
        self.original_text = text
        self.setWindowTitle(title)
        self.resize(1000, 800)

        # Add Command+W shortcut
        shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        shortcut.activated.connect(self.close)

        layout = QVBoxLayout(self)

        # Button row
        button_layout = QHBoxLayout()

        # Translate button
        translate_btn = QPushButton("한글로 번역")
        translate_btn.setFixedWidth(120)
        translate_btn.clicked.connect(self.translate_text)
        button_layout.addWidget(translate_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Text area
        self.text_edit = QTextEdit()
        self.text_edit.setFocusPolicy(Qt.StrongFocus)
        self.text_edit.setTextInteractionFlags(Qt.TextEditorInteraction)
        try:
            self.text_edit.setMarkdown(text)
        except AttributeError:
            self.text_edit.setPlainText(text)

        # Make text larger
        self.text_edit.setStyleSheet("font-size: 14px;")

        layout.addWidget(self.text_edit)

    def closeEvent(self, event):
        if self in self.windows:
            self.windows.remove(self)
        super().closeEvent(event)

    def translate_text(self):
        try:
            translated_text = translate(self.original_text)
            try:
                self.text_edit.setMarkdown(translated_text)
            except AttributeError:
                self.text_edit.setPlainText(translated_text)
        except Exception as e:
            self.text_edit.setPlainText(f"Translation error: {str(e)}")


class BlockWidget(QFrame):
    def __init__(self, title: str, text: str, windows: List["TextWindow"]):
        super().__init__()
        self.windows = windows
        self.text = text
        # Style: simple rounded rectangle
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid #ccc; border-radius: 8px; padding: 8px; margin: 4px; }"
        )

        layout = QVBoxLayout(self)

        # Title and button row
        title_row = QHBoxLayout()

        # Title label
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        title_row.addWidget(title_label)

        # Copy button
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedWidth(80)
        copy_btn.clicked.connect(self.copy_text)
        title_row.addWidget(copy_btn)

        # New Window button
        new_window_btn = QPushButton("New Window")
        new_window_btn.setFixedWidth(100)
        new_window_btn.clicked.connect(lambda: self.open_new_window(title, text))
        title_row.addWidget(new_window_btn)

        layout.addLayout(title_row)

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

    def open_new_window(self, title: str, text: str):
        window = TextWindow(title, text, self.windows)
        window.show()

    def copy_text(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text)


class ChatWindow(QWidget):
    def __init__(self, generator: Callable[[str], str]):
        super().__init__()
        self.generator = generator
        self.setWindowTitle(f"test {generator.__name__}")
        self.resize(800, 600)
        self.text_windows = []  # Keep track of text windows

        # Add Command+W shortcut
        shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        shortcut.activated.connect(self.close)

        # Main vertical layout: input area (1/3) on top, chat area (2/3) at bottom
        main_layout = QVBoxLayout(self)

        # Input area
        input_area = QWidget()
        input_layout = QVBoxLayout(input_area)
        self.input_edit = QTextEdit()
        self.input_edit.setText("Tesla")
        submit_btn = QPushButton("Submit")
        submit_btn.setFixedWidth(80)
        submit_btn.clicked.connect(self.add_message)

        # Add Command+Enter shortcut
        submit_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        submit_shortcut.activated.connect(self.add_message)

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
        user_block = BlockWidget("You", text, self.text_windows)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, user_block)

        # Call generator (may sleep)
        try:
            response_text = self.generator(text)
        except Exception as e:
            print(f"Error in generator: {e}, {traceback.format_exc()}")
            response_text = f"Error: {e} \n {traceback.format_exc()}"

        # Add the response block
        title = self.generator.__name__
        answer_block = BlockWidget(title, response_text, self.text_windows)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, answer_block)
        self.input_edit.clear()


list_of_methods = []


def append_to_methods(func):
    list_of_methods.append(func)
    return func


def run_runners():
    app = QApplication(sys.argv)
    chat_windows = []  # Renamed from 'windows' for clarity
    sel_window = QWidget()
    sel_window.setWindowTitle("Select Runner")

    def close_all_windows():
        # Close all TextWindows first
        for cw in chat_windows:
            # Iterate over a copy of the list as items are removed during iteration
            for tw in list(cw.text_windows):
                tw.close()
        # Close all ChatWindows
        for cw in list(chat_windows):  # Iterate over a copy
            cw.close()
        sel_window.close()  # Close the selection window itself

    # Add Command+W shortcut
    shortcut = QShortcut(QKeySequence("Ctrl+W"), sel_window)
    shortcut.activated.connect(close_all_windows)

    layout = QVBoxLayout(sel_window)
    for func in list_of_methods:
        btn = QPushButton(func.__name__)

        # Pass chat_windows list to the handler
        def handler(checked, f=func, current_chat_windows=chat_windows):
            print(f)
            cw = ChatWindow(f)
            current_chat_windows.append(cw)
            cw.show()

        btn.clicked.connect(handler)
        layout.addWidget(btn)
    sel_window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    pass
