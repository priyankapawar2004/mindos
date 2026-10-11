import sys
import os
import subprocess
import webbrowser
import datetime
import warnings
import platform
import html
import json
import urllib.request
import urllib.error
from pathlib import Path

import pyautogui
from dotenv import load_dotenv

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextBrowser,
    QLineEdit,
    QPushButton,
    QLabel,
    QFrame,
    QMessageBox,
    QSizePolicy,
)

# --------------------------------------------------
# ENVIRONMENT
# --------------------------------------------------

load_dotenv()
warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_NAME = "MindOS"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
BASE_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIR = BASE_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


# --------------------------------------------------
# GREEN NATURE THEME
# --------------------------------------------------

GREEN_THEME_QSS = """
QMainWindow {
    background-color: #F4F8F1;
}
QWidget {
    font-family: "Segoe UI";
    font-size: 13px;
    color: #23412C;
}
QFrame#sidebar {
    background-color: #FFFFFF;
    border: 1px solid #DCE8D7;
    border-radius: 16px;
}
QFrame#chat_panel {
    background-color: #FFFFFF;
    border: 1px solid #DCE8D7;
    border-radius: 16px;
}
QLabel {
    background: transparent;
    color: #23412C;
}
QLabel#brand {
    color: #3F7D45;
    font-size: 24px;
    font-weight: bold;
}
QLabel#subtitle {
    color: #789078;
    font-size: 12px;
}
QLabel#section_title {
    color: #23412C;
    font-size: 17px;
    font-weight: bold;
}
QLabel#status {
    color: #527358;
    font-size: 12px;
}
QTextBrowser {
    background-color: #FAFCF8;
    border: 1px solid #E5EDE1;
    border-radius: 12px;
    padding: 12px;
    selection-background-color: #62A65A;
    selection-color: white;
}
QLineEdit {
    background-color: #FFFFFF;
    color: #23412C;
    border: 1px solid #C8DCC3;
    border-radius: 12px;
    padding: 12px;
    font-size: 14px;
}
QLineEdit:focus {
    border: 2px solid #62A65A;
}
QPushButton {
    background-color: #62A65A;
    color: white;
    font-weight: bold;
    border: none;
    border-radius: 10px;
    padding: 10px 15px;
}
QPushButton:hover {
    background-color: #4E9148;
}
QPushButton:pressed {
    background-color: #3D7539;
}
QPushButton:disabled {
    background-color: #B8CBB3;
    color: #F4F8F1;
}
QPushButton#secondary {
    background-color: #EEF5E9;
    color: #315D35;
    border: 1px solid #DCE8D7;
    text-align: left;
    padding: 11px;
}
QPushButton#secondary:hover {
    background-color: #E0EED9;
}
QPushButton#clear {
    background-color: transparent;
    color: #648066;
    border: 1px solid #DCE8D7;
}
QPushButton#clear:hover {
    background-color: #EEF5E9;
}
"""


# --------------------------------------------------
# OLLAMA WORKER THREAD
# --------------------------------------------------

class AIWorker(QThread):
    """Runs the local model request away from the GUI thread."""
    answer_ready = Signal(str, str)
    # Emits (reply, error_message); error_message is empty on success.

    def __init__(self, prompt, conversation, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.conversation = list(conversation)

    def run(self):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are MindOS, a helpful desktop AI assistant. "
                    "Be clear, friendly, and practical. You run locally. "
                    "Never claim to have performed desktop actions unless "
                    "the application confirms they succeeded. You cannot "
                    "directly control the computer; use the app's supported "
                    "and user-approved quick actions for desktop tasks."
                ),
            }
        ]
        messages.extend(self.conversation)
        messages.append({"role": "user", "content": self.prompt})

        payload = {
             "model": OLLAMA_MODEL,
            "messages": messages,
             "stream": False,
             "think": False,
               "keep_alive": "15m",
                "options": {
        "num_predict": 256,
    },
}
        request = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            reply = result.get("message", {}).get("content", "").strip()
            if not reply:
                reply = "I received an empty response. Please try again."
            self.answer_ready.emit(reply, "")
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            self.answer_ready.emit(
                "",
                "I couldn't reach Ollama at "
                f"{OLLAMA_URL}.\n\n"
                "Make sure the Ollama app is running and the model is "
                f"installed (`{OLLAMA_MODEL}`).\n\nDetails: {reason}",
            )
        except TimeoutError:
            self.answer_ready.emit(
                "",
                "The local model took too long to respond. Please try again.",
            )
        except Exception as error:
            self.answer_ready.emit(
                "",
                f"Something went wrong while talking to Ollama:\n{error}",
            )


# --------------------------------------------------
# MINDOS DASHBOARD
# --------------------------------------------------

class MindOSDashboard(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("MindOS | AI Desktop Assistant")
        self.resize(1120, 720)
        self.setMinimumSize(760, 540)
        self.setStyleSheet(GREEN_THEME_QSS)

        self.conversation = []
        self.busy = False
        self.worker = None

        self.setup_ui()
        self.check_ollama()
        self.show_welcome()

    # --------------------------------------------------
    # UI HELPERS
    # --------------------------------------------------

    def make_label(self, text, object_name=None):
        label = QLabel(text)
        if object_name:
            label.setObjectName(object_name)
        return label

    def make_button(self, text, callback, secondary=False):
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        if secondary:
            button.setObjectName("secondary")
        return button

    # --------------------------------------------------
    # UI SETUP
    # --------------------------------------------------

    def setup_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(225)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(14)

        sidebar_layout.addWidget(self.make_label("🌿 MindOS", "brand"))
        sidebar_layout.addWidget(
            self.make_label("YOUR PERSONAL AI ASSISTANT", "subtitle")
        )
        sidebar_layout.addSpacing(22)
        sidebar_layout.addWidget(self.make_label("WORKSPACE", "subtitle"))

        self.home_btn = self.make_button("⌂   Home", self.show_welcome, True)
        self.new_chat_btn = self.make_button(
            "＋   New conversation", self.new_conversation, True
        )
        sidebar_layout.addWidget(self.home_btn)
        sidebar_layout.addWidget(self.new_chat_btn)

        sidebar_layout.addSpacing(18)
        sidebar_layout.addWidget(self.make_label("QUICK ACTIONS", "subtitle"))
        sidebar_layout.addWidget(
            self.make_button("✦   Ask AI anything", self.focus_input, True)
        )
        sidebar_layout.addWidget(
            self.make_button(
                "▣   Open Notepad",
                lambda: self.request_automation("open notepad"),
                True,
            )
        )
        sidebar_layout.addWidget(
            self.make_button(
                "▣   Open Calculator",
                lambda: self.request_automation("open calculator"),
                True,
            )
        )
        sidebar_layout.addWidget(
            self.make_button(
                "◉   Take screenshot",
                lambda: self.request_automation("take screenshot"),
                True,
            )
        )
        sidebar_layout.addStretch()

        self.ai_status = self.make_label("● Checking local AI...", "status")
        self.ai_status.setWordWrap(True)
        sidebar_layout.addWidget(self.ai_status)
        sidebar_layout.addWidget(
            self.make_label("MindOS • Local desktop app", "subtitle")
        )

        chat_panel = QFrame()
        chat_panel.setObjectName("chat_panel")
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(22, 20, 22, 18)
        chat_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        header_text.addWidget(
            self.make_label("Your AI workspace", "section_title")
        )
        header_text.addWidget(
            self.make_label(
                "A calm space to think, create and get things done.",
                "subtitle",
            )
        )
        header_layout.addLayout(header_text)
        header_layout.addStretch()

        self.clear_btn = QPushButton("Clear chat")
        self.clear_btn.setObjectName("clear")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.new_conversation)
        header_layout.addWidget(self.clear_btn)
        chat_layout.addLayout(header_layout)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #E5EDE1;")
        chat_layout.addWidget(separator)

        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        self.chat_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        chat_layout.addWidget(self.chat_display, 1)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(
            "Message MindOS... (try 'what is Python?')"
        )
        self.input_field.returnPressed.connect(self.send_message)
        self.input_field.setClearButtonEnabled(True)

        self.send_btn = QPushButton("Send  ➤")
        self.send_btn.setMinimumWidth(100)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.input_field, 1)
        input_layout.addWidget(self.send_btn)
        chat_layout.addLayout(input_layout)

        footer = self.make_label(
            "AI responses may be inaccurate. "
            "Desktop actions require your approval.",
            "subtitle",
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chat_layout.addWidget(footer)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(chat_panel, 1)
        self.setCentralWidget(root)

    # --------------------------------------------------
    # CHAT DISPLAY
    # --------------------------------------------------

    def append_message(self, sender, message, kind="assistant"):
        safe_message = html.escape(str(message)).replace("\n", "<br>")

        if kind == "user":
            name, bubble_color, alignment, text_color = (
                "You", "#E5F2DF", "right", "#23412C"
            )
        elif kind == "system":
            name, bubble_color, alignment, text_color = (
                "MindOS • System", "#F0F5EC", "left", "#527358"
            )
        else:
            name, bubble_color, alignment, text_color = (
                "MindOS", "#FFFFFF", "left", "#263D2B"
            )

        message_html = f"""
        <div style="margin: 12px 4px; text-align: {alignment};">
            <div style="color: #789078; font-size: 11px; margin-bottom: 5px;">
                {html.escape(name)}
            </div>
            <span style="
                display: inline-block;
                background-color: {bubble_color};
                color: {text_color};
                border: 1px solid #DCE8D7;
                border-radius: 12px;
                padding: 11px 14px;
                line-height: 1.5;">
                {safe_message}
            </span>
        </div>
        """
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.insertHtml(message_html)
        self.chat_display.insertHtml("<br>")
        self.chat_display.ensureCursorVisible()

    def show_welcome(self):
        self.chat_display.clear()
        self.append_message(
            "MindOS",
            "Hello! Welcome to MindOS 🌿\n\n"
            "I'm your AI desktop assistant, powered by a local model. "
            "You can ask questions, get programming help, or request "
            "supported desktop actions.\n\n"
            "Try asking:\n"
            "• What is Python?\n"
            "• Explain object-oriented programming.\n"
            "• Open Notepad\n"
            "• What time is it?",
            "assistant",
        )

    def new_conversation(self):
        if self.busy:
            self.append_message(
                "MindOS", "Please wait for the current reply to finish.", "system"
            )
            return
        self.conversation.clear()
        self.show_welcome()
        self.input_field.setFocus()

    def focus_input(self):
        self.input_field.setFocus()

    # --------------------------------------------------
    # OLLAMA CONNECTION
    # --------------------------------------------------

    def check_ollama(self):
        """Quickly check the local Ollama tags endpoint."""
        tags_url = OLLAMA_URL.rsplit("/", 1)[0] + "/tags"
        try:
            with urllib.request.urlopen(tags_url, timeout=3) as response:
                data = json.loads(response.read().decode("utf-8"))
            installed = [item.get("name", "") for item in data.get("models", [])]
            model_base = OLLAMA_MODEL.split(":")[0]
            if OLLAMA_MODEL in installed or any(
                name.split(":")[0] == model_base for name in installed
            ):
                self.ai_status.setText(f"● Local AI ready ({OLLAMA_MODEL})")
            else:
                self.ai_status.setText("● Ollama running • check model name")
                self.append_message(
                    "MindOS",
                    f"Ollama is running, but `{OLLAMA_MODEL}` was not found "
                    "in its model list. Check the model name in your terminal.",
                    "system",
                )
        except Exception:
            self.ai_status.setText("● Ollama not detected")
            self.append_message(
                "MindOS",
                "I couldn't contact Ollama yet. Make sure the Ollama app is "
                "running. Your installed model should be "
                f"`{OLLAMA_MODEL}`. You can still use the desktop quick actions.",
                "system",
            )

    # --------------------------------------------------
    # DESKTOP COMMAND RECOGNITION
    # --------------------------------------------------

    def identify_automation(self, command):
        text = command.lower().strip()
        words = set(text.replace("?", "").replace("!", "").split())

        if "notepad" in words and words.intersection({"open", "launch", "start"}):
            return "notepad"
        if (
            words.intersection({"calculator", "calc"})
            and words.intersection({"open", "launch", "start"})
        ):
            return "calculator"
        if (
            words.intersection({"terminal", "cmd"})
            and words.intersection({"open", "launch", "start"})
        ):
            return "terminal"
        if "youtube" in words and words.intersection({"open", "launch", "visit"}):
            return "youtube"
        if "google" in words and words.intersection({"open", "launch", "visit"}):
            return "google"
        if "github" in words and words.intersection({"open", "launch", "visit"}):
            return "github"
        if "screenshot" in words and words.intersection({"take", "capture"}):
            return "screenshot"
        return None

    # --------------------------------------------------
    # APPROVED DESKTOP AUTOMATION
    # --------------------------------------------------

    def request_automation(self, command):
        action = self.identify_automation(command)
        if action is None:
            self.append_message(
                "MindOS",
                "That desktop action isn't supported yet. Try opening Notepad, "
                "Calculator, Command Prompt, Google, YouTube, GitHub, or taking "
                "a screenshot.",
                "assistant",
            )
            return

        descriptions = {
            "notepad": "Open the Windows Notepad application.",
            "calculator": "Open the Windows Calculator application.",
            "terminal": "Open the Windows Command Prompt.",
            "youtube": "Open youtube.com in your browser.",
            "google": "Open google.com in your browser.",
            "github": "Open github.com in your browser.",
            "screenshot": (
                "Capture a screenshot of your current screen and save it "
                "in the MindOS screenshots folder."
            ),
        }
        answer = QMessageBox.question(
            self,
            "Approve desktop action",
            f"Do you want MindOS to perform this action?\n\n"
            f"{descriptions[action]}\n\n"
            "Only approve if you intended this action.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.append_message(
                "MindOS", "Action cancelled. Nothing was executed.", "system"
            )
            return

        try:
            result = self.execute_automation(action)
        except Exception as error:
            result = f"Action failed: {error}"
        self.append_message("MindOS", result, "assistant")

    def execute_automation(self, action):
        is_windows = platform.system() == "Windows"

        if action == "notepad":
            if not is_windows:
                return "Notepad is supported only on Windows."
            subprocess.Popen(["notepad.exe"])
            return "Notepad opened successfully."

        if action == "calculator":
            if not is_windows:
                return "Windows Calculator is supported only on Windows."
            subprocess.Popen(["calc.exe"])
            return "Calculator opened successfully."

        if action == "terminal":
            if not is_windows:
                return "This terminal command is supported only on Windows."
            subprocess.Popen(["cmd.exe"])
            return "Command Prompt opened successfully."

        websites = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
        }
        if action in websites:
            opened = webbrowser.open(websites[action])
            if opened:
                return f"Opened {websites[action]}"
            return (
                "I sent the request to your browser. Please check whether "
                "the website opened."
            )

        if action == "screenshot":
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = SCREENSHOT_DIR / f"screenshot_{timestamp}.png"
            pyautogui.screenshot().save(str(filename))
            return f"Screenshot saved to:\n{filename}"

        return "Unknown desktop action."

    # --------------------------------------------------
    # MESSAGE HANDLING
    # --------------------------------------------------

    def send_message(self):
        if self.busy:
            return

        text = self.input_field.text().strip()
        if not text:
            return

        self.input_field.clear()
        self.append_message("You", text, "user")

        normalized = text.lower().strip().rstrip("?!.")

        if normalized in {
            "time",
            "what time is it",
            "tell me the time",
            "current time",
            "what is the time",
        }:
            now = datetime.datetime.now().strftime("%I:%M %p")
            self.append_message(
                "MindOS", f"The current time is {now}.", "assistant"
            )
            return

        action = self.identify_automation(text)
        if action is not None:
            self.request_automation(text)
            return

        self.busy = True
        self.send_btn.setEnabled(False)
        self.send_btn.setText("Thinking...")
        self.ai_status.setText("● Thinking locally...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        self.pending_prompt = text
        self.worker = AIWorker(text, self.conversation, self)
        self.worker.answer_ready.connect(self.on_ai_answer)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_ai_answer(self, answer, error_message):
        QApplication.restoreOverrideCursor()
        if error_message:
            self.append_message("MindOS", error_message, "system")
            return

        self.append_message("MindOS", answer, "assistant")
        # Store only successful exchanges as context for the next turn.
        # Keep the recent conversation short to limit memory and prompt size.
        # The worker used the old history plus this current prompt.
        # The latest user text is available from the last user bubble only,
        # so capture it in self.pending_prompt before starting the worker.
        self.conversation.append(
            {"role": "user", "content": getattr(self, "pending_prompt", "")}
        )
        self.conversation.append({"role": "assistant", "content": answer})
        self.conversation = self.conversation[-20:]

    def on_worker_finished(self):
        QApplication.restoreOverrideCursor()
        self.busy = False
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Send  ➤")
        self.ai_status.setText(f"● Local AI ({OLLAMA_MODEL})")
        self.input_field.setFocus()
        self.worker = None

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self,
                "MindOS is still thinking",
                "Please wait for the current local AI response to finish "
                "before closing MindOS.",
            )
            event.ignore()
            return
        event.accept()


# --------------------------------------------------
# APPLICATION START
# --------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))

    window = MindOSDashboard()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
