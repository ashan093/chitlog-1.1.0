"""Theme-aware login and local recovery screens."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.config import APP_NAME
from chitlog.core.security import SecurityError
from chitlog.services.authentication_service import AuthenticationService
from chitlog.ui.setup_wizard import SecretInput
from chitlog.ui.theme import SPACE, stylesheet
from chitlog.ui.widgets import Background, button, text_label


class ReservedInlineError(QLabel):
    """Inline error area with stable geometry so forms never jump or clip."""

    def __init__(self, minimum_height: int = 42):
        super().__init__("")
        self.setProperty("role", "error")
        self.setWordWrap(True)
        self.setMinimumHeight(minimum_height)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def show_error(self, message: str) -> None:
        self.setText(message)

    def clear_error(self) -> None:
        self.clear()


class RecoveryDialog(QDialog):
    """Verify both configured recovery answers before replacing credentials."""

    secret_reset = Signal(str)

    def __init__(
        self,
        service: AuthenticationService,
        theme_name: str,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.theme_name = theme_name
        self.method = service.login_method()

        self.setWindowTitle(f"{APP_NAME} — Recover access")
        self.setModal(True)
        self.resize(680, 600)
        self.setMinimumSize(620, 560)
        self.setStyleSheet(stylesheet(theme_name))

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        root.setSpacing(SPACE["md"])

        root.addWidget(text_label("Recover access", "pageTitle"))
        self.description = text_label(
            "Answer both recovery questions. Answers are checked locally and are never displayed.",
            "muted",
        )
        root.addWidget(self.description)

        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)

        self._build_questions_page()
        self._build_reset_page()

        footer = QHBoxLayout()
        footer.addStretch()
        self.cancel_button = button("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)

    def _build_questions_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["md"])

        # Keep this area in the layout even when empty. Previously, making the
        # error label appear changed the page height after layout, which could
        # temporarily clip the answer fields until the user resized the dialog.
        self.recovery_error = ReservedInlineError()
        layout.addWidget(self.recovery_error)

        questions = self.service.recovery_questions()
        self.answer_inputs: list[SecretInput] = []
        for item in questions:
            layout.addWidget(text_label(item.question, "heading"))
            field = SecretInput()
            field.set_placeholder("Your answer")
            field.edit.setMaxLength(200)
            field.edit.returnPressed.connect(self._verify_answers)
            field.edit.textChanged.connect(self.recovery_error.clear_error)
            layout.addWidget(field)
            self.answer_inputs.append(field)

        layout.addStretch()
        verify = button("Verify answers", "primary")
        verify.clicked.connect(self._verify_answers)
        layout.addWidget(verify, 0, Qt.AlignmentFlag.AlignRight)
        self.pages.addWidget(page)

    def _build_reset_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["md"])

        layout.addWidget(text_label("Choose a new login method", "heading"))
        layout.addWidget(
            text_label(
                "You may keep the current method or switch between PIN and Password.",
                "muted",
            )
        )

        method_row = QHBoxLayout()
        self.reset_pin = QRadioButton("PIN")
        self.reset_password = QRadioButton("Password")
        self.reset_method_group = QButtonGroup(self)
        self.reset_method_group.setExclusive(True)
        self.reset_method_group.addButton(self.reset_pin)
        self.reset_method_group.addButton(self.reset_password)
        method_row.addWidget(self.reset_pin)
        method_row.addWidget(self.reset_password)
        method_row.addStretch()
        layout.addLayout(method_row)

        self.reset_error = ReservedInlineError()
        layout.addWidget(self.reset_error)

        self.new_secret = SecretInput()
        self.confirm_secret = SecretInput()
        self.new_label = QLabel()
        self.confirm_label = QLabel("Confirm")

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])
        form.addRow(self.new_label, self.new_secret)
        form.addRow(self.confirm_label, self.confirm_secret)
        layout.addLayout(form)

        self.new_secret.edit.textChanged.connect(self.reset_error.clear_error)
        self.confirm_secret.edit.textChanged.connect(self.reset_error.clear_error)
        self.confirm_secret.edit.returnPressed.connect(self._reset_credentials)

        self.reset_button = button("Save new login", "primary")
        self.reset_button.clicked.connect(self._reset_credentials)
        layout.addStretch()
        layout.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignRight)
        self.pages.addWidget(page)

        self.reset_pin.toggled.connect(
            lambda checked: checked and self._configure_reset_method("pin")
        )
        self.reset_password.toggled.connect(
            lambda checked: checked and self._configure_reset_method("password")
        )
        if self.method == "pin":
            self.reset_pin.setChecked(True)
        else:
            self.reset_password.setChecked(True)

    def _selected_reset_method(self) -> str:
        return "pin" if self.reset_pin.isChecked() else "password"

    def _configure_reset_method(self, method: str) -> None:
        self.reset_error.clear_error()
        self.new_secret.clear()
        self.confirm_secret.clear()
        label = "PIN" if method == "pin" else "Password"
        self.new_label.setText(f"New {label}")
        self.reset_button.setText(f"Save new {label}")
        if method == "pin":
            self.new_secret.configure_for_pin()
            self.confirm_secret.configure_for_pin()
        else:
            self.new_secret.configure_for_password()
            self.confirm_secret.configure_for_password()
        self.new_secret.edit.setFocus()

    def _verify_answers(self) -> None:
        self.recovery_error.clear_error()
        answers = [field.text() for field in self.answer_inputs]
        if not all(answers):
            self.recovery_error.show_error("Answer both security questions.")
            return
        if not self.service.verify_recovery_answers(answers):
            self.recovery_error.show_error(
                "The recovery answers did not match. Try again."
            )
            return

        for field in self.answer_inputs:
            field.clear()
        self.description.setText(
            "Recovery answers verified. Choose PIN or Password and create a new login secret."
        )
        self.pages.setCurrentIndex(1)
        self._configure_reset_method(self._selected_reset_method())

    def _reset_credentials(self) -> None:
        self.reset_error.clear_error()
        method = self._selected_reset_method()
        try:
            self.service.reset_credentials(
                method,
                self.new_secret.text(),
                self.confirm_secret.text(),
            )
        except SecurityError as error:
            self.reset_error.show_error(str(error))
            return
        except RuntimeError:
            self.reset_error.show_error("ChitLog could not update the login credentials.")
            return

        self.new_secret.clear()
        self.confirm_secret.clear()
        self.secret_reset.emit(method)
        self.accept()


class LoginDialog(QDialog):
    """Startup authentication screen with unlimited normal retries."""

    def __init__(
        self,
        assets: Path,
        service: AuthenticationService,
        theme_name: str,
        parent=None,
        *,
        locked: bool = False,
    ):
        super().__init__(parent)
        self.assets = assets
        self.service = service
        self.theme_name = theme_name
        self.locked = bool(locked)
        self.method = service.login_method()

        self.setWindowTitle(
            f"{APP_NAME} — {'Locked' if self.locked else 'Login'}"
        )
        icon_path = assets / "chit.png"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(900, 610)
        self.setMinimumSize(760, 540)
        self.setStyleSheet(stylesheet(theme_name))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.background = Background(assets)
        self.background.theme_name = theme_name
        root.addWidget(self.background)

        overlay = QVBoxLayout(self.background)
        overlay.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        overlay.addStretch()

        card = QFrame()
        card.setProperty("role", "glass")
        card.setMaximumWidth(500)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 34, 36, 34)
        card_layout.setSpacing(SPACE["md"])

        logo = QLabel()
        pixmap = QPixmap(str(assets / "chit.png"))
        if pixmap.isNull():
            logo.setText(APP_NAME)
            logo.setProperty("role", "title")
        else:
            logo.setPixmap(
                pixmap.scaled(
                    300,
                    135,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(logo)

        card_layout.addWidget(
            text_label(
                "ChitLog is locked" if self.locked else "Welcome back",
                "pageTitle",
            )
        )
        self.prompt_label = text_label("", "muted")
        card_layout.addWidget(self.prompt_label)

        self.error = ReservedInlineError(34)
        card_layout.addWidget(self.error)

        self.secret = SecretInput()
        self.secret.edit.returnPressed.connect(self._login)
        self.secret.edit.textChanged.connect(self.error.clear_error)
        card_layout.addWidget(self.secret)

        login_button = button("Unlock" if self.locked else "Login", "primary")
        login_button.clicked.connect(self._login)
        card_layout.addWidget(login_button)

        self.forgot_button = QPushButton()
        self.forgot_button.setFlat(True)
        self.forgot_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forgot_button.clicked.connect(self._open_recovery)
        card_layout.addWidget(self.forgot_button)

        self.status = text_label("", "muted")
        self.status.setVisible(False)
        card_layout.addWidget(self.status)

        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(card)
        center.addStretch()
        overlay.addLayout(center)
        overlay.addStretch()

        self._configure_login_method(self.method)
        self.secret.edit.setFocus()

    def _configure_login_method(self, method: str) -> None:
        self.method = method
        self.secret.clear()
        label = "PIN" if method == "pin" else "Password"
        if method == "pin":
            self.secret.configure_for_pin()
        else:
            self.secret.configure_for_password()
        self.secret.edit.setAccessibleName(label)
        action = "unlock" if self.locked else "open"
        self.prompt_label.setText(f"Enter your {label} to {action} ChitLog.")
        self.forgot_button.setText(f"Forgot {label}?")

    def _login(self) -> None:
        self.error.clear_error()
        candidate = self.secret.text()
        if not candidate:
            self.error.show_error(
                "Enter your PIN." if self.method == "pin" else "Enter your password."
            )
            return

        if not self.service.verify_login(candidate):
            self.secret.clear()
            self.error.show_error(
                "Incorrect PIN. Try again."
                if self.method == "pin"
                else "Incorrect password. Try again."
            )
            self.secret.edit.setFocus()
            return

        self.secret.clear()
        self.accept()

    def _open_recovery(self) -> None:
        recovery = RecoveryDialog(self.service, self.theme_name, self)
        recovery.secret_reset.connect(self._recovery_completed)
        recovery.exec()

    def _recovery_completed(self, method: str) -> None:
        self._configure_login_method(method)
        label = "PIN" if method == "pin" else "password"
        self.error.clear_error()
        self.status.setText(f"Your {label} was reset. Sign in with the new {label}.")
        self.status.setVisible(True)
        self.secret.edit.setFocus()
