"""First-run setup wizard for ChitLog."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from chitlog.core.config import APP_NAME
from chitlog.core.security import (
    SecurityError,
    SecurityQuestionAnswer,
    validate_secret,
    validate_security_questions,
)
from chitlog.services.setup_service import (
    CURRENCIES,
    SetupService,
    SetupSubmission,
)
from chitlog.ui.theme import SCOOTER, SPACE, THEMES, resolve_theme, stylesheet
from chitlog.ui.widgets import text_label


COMMON_SECURITY_QUESTIONS = (
    "What was the name of your first school?",
    "What was the name of your first pet?",
    "What was your childhood nickname?",
    "What is the name of a memorable place from your childhood?",
    "What was the title of a book or movie you strongly remember?",
    "What private phrase can you reliably remember?",
)


def _eye_icon(slashed: bool) -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor(SCOOTER), 2.0)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(4, 7, 16, 10)

    painter.setBrush(QColor(SCOOTER))
    painter.drawEllipse(10, 10, 4, 4)

    if slashed:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(5, 5, 19, 19)

    painter.end()
    return QIcon(pixmap)


class SecretInput(QWidget):
    """PIN/password field with an eye-button show/hide control."""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.edit, 1)

        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setIcon(_eye_icon(False))
        self.toggle.setToolTip("Show value")
        self.toggle.setAccessibleName("Show value")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.toggled.connect(self._toggle_visibility)
        layout.addWidget(self.toggle)

    def _toggle_visibility(self, checked: bool) -> None:
        self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.toggle.setIcon(_eye_icon(checked))
        if checked:
            self.toggle.setToolTip("Hide value")
            self.toggle.setAccessibleName("Hide value")
        else:
            self.toggle.setToolTip("Show value")
            self.toggle.setAccessibleName("Show value")

    def text(self) -> str:
        return self.edit.text()

    def clear(self) -> None:
        self.edit.clear()
        self.toggle.setChecked(False)

    def set_placeholder(self, text: str) -> None:
        self.edit.setPlaceholderText(text)

    def configure_for_pin(self) -> None:
        validator = QRegularExpressionValidator(
            QRegularExpression(r"\d{0,12}"),
            self.edit,
        )
        self.edit.setValidator(validator)
        self.edit.setMaxLength(12)
        self.set_placeholder("4 to 12 digits")

    def configure_for_password(self) -> None:
        self.edit.setValidator(None)
        self.edit.setMaxLength(128)
        self.set_placeholder("At least 8 characters")


class InlineError(QLabel):
    """Validation feedback displayed inside the current page."""

    def __init__(self):
        super().__init__("")

        self.setProperty("role", "error")
        self.setWordWrap(True)
        self.setVisible(False)

    def show_error(self, message: str) -> None:
        self.setText(message)
        self.setVisible(True)

    def clear_error(self) -> None:
        self.clear()
        self.setVisible(False)


class BasePage(QWizardPage):
    """
    Each page paints its own themed background.

    This fixes the Dark-theme preview issue where the wizard body stayed white
    while the text switched to light colors.
    """

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()

        self.setTitle("")
        self.setSubTitle("")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(
            SPACE["xl"],
            SPACE["lg"],
            SPACE["xl"],
            SPACE["lg"],
        )
        self.root.setSpacing(SPACE["md"])

        self.root.addWidget(text_label(title, "pageTitle"))

        if subtitle:
            self.root.addWidget(text_label(subtitle, "muted"))

        self.error = InlineError()
        self.root.addWidget(self.error)

    def apply_page_theme(self, theme_name: str) -> None:
        actual = resolve_theme(theme_name)
        theme = THEMES[actual]

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.background))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Base, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.field))
        palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Button, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(SCOOTER))

        self.setPalette(palette)
        self.update()


class WelcomePage(BasePage):
    def __init__(self, assets: Path):
        super().__init__(
            f"Welcome to {APP_NAME}",
            "Set up ChitLog once, then use your PIN or password on future starts.",
        )

        row = QHBoxLayout()
        row.setSpacing(SPACE["lg"])

        logo = QLabel()
        pixmap = QPixmap(str(assets / "chit.png"))

        if pixmap.isNull():
            logo.setText(APP_NAME)
            logo.setProperty("role", "title")
        else:
            logo.setPixmap(
                pixmap.scaled(
                    300,
                    150,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        row.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        details = QVBoxLayout()
        details.addWidget(text_label("What happens here", "heading"))
        details.addWidget(
            text_label(
                "• Choose PIN or Password\n"
                "• Configure 2 recovery questions\n"
                "• Choose your currency\n"
                "• Choose Light, Dark, or System theme\n"
                "• Finish and open ChitLog",
                "muted",
            )
        )
        details.addSpacing(SPACE["sm"])
        details.addWidget(
            text_label(
                "Your login secret and recovery answers are stored as "
                "Argon2id hashes, not as readable text.",
                "muted",
            )
        )

        row.addLayout(details, 1)
        self.root.addLayout(row)
        self.root.addStretch()


class LoginMethodPage(BasePage):
    def __init__(self):
        super().__init__(
            "Choose your login method",
            "You can change this later in Settings.",
        )

        self.pin = QRadioButton("PIN")
        self.password = QRadioButton("Password")
        self.pin.setChecked(True)

        self.root.addWidget(self.pin)
        self.root.addWidget(text_label("Fast sign-in using 4 to 12 digits.", "muted"))
        self.root.addSpacing(SPACE["sm"])
        self.root.addWidget(self.password)
        self.root.addWidget(
            text_label("A password must contain at least 8 characters.", "muted")
        )
        self.root.addStretch()


class CredentialPage(BasePage):
    def __init__(self):
        super().__init__(
            "Create your login secret",
            "Use the eye button when you need to check what you typed.",
        )

        self.secret_label = QLabel("PIN")
        self.secret = SecretInput()
        self.confirm = SecretInput()

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE["lg"])
        form.setVerticalSpacing(SPACE["md"])
        form.addRow(self.secret_label, self.secret)
        form.addRow("Confirm", self.confirm)

        self.root.addLayout(form)

        self.hint = text_label("", "muted")
        self.root.addWidget(self.hint)
        self.root.addStretch()

        self.secret.edit.textChanged.connect(self.error.clear_error)
        self.confirm.edit.textChanged.connect(self.error.clear_error)

    def initializePage(self) -> None:
        self.error.clear_error()

        method = self.wizard().selected_login_method()

        if method == "pin":
            self.secret_label.setText("PIN")
            self.secret.configure_for_pin()
            self.confirm.configure_for_pin()
            self.hint.setText("PINs accept digits only.")
        else:
            self.secret_label.setText("Password")
            self.secret.configure_for_password()
            self.confirm.configure_for_password()
            self.hint.setText("Use a longer password that is difficult to guess.")

    def validatePage(self) -> bool:
        self.error.clear_error()

        try:
            self.wizard().capture_secret(
                self.secret.text(),
                self.confirm.text(),
            )
            return True
        except SecurityError as error:
            self.error.show_error(str(error))
            return False


class SecurityQuestionRow(QWidget):
    def __init__(self, number: int, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        layout.addWidget(text_label(f"Security question {number}", "heading"))

        self.choice = QComboBox()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("Type your custom security question")
        self.custom.setMaxLength(120)
        self.custom.setVisible(False)

        self.answer = SecretInput()
        self.answer.edit.setMaxLength(200)
        self.answer.set_placeholder("Answer")

        layout.addWidget(self.choice)
        layout.addWidget(self.custom)

        answer_row = QFormLayout()
        answer_row.setHorizontalSpacing(SPACE["lg"])
        answer_row.addRow("Answer", self.answer)
        layout.addLayout(answer_row)

        self.choice.currentIndexChanged.connect(self._selection_changed)
        self.rebuild_choices()

    def _selection_changed(self) -> None:
        custom_selected = self.choice.currentData() == "__custom__"
        self.custom.setVisible(custom_selected)
        if custom_selected:
            self.custom.setFocus()

    def rebuild_choices(self, blocked: set[str] | None = None) -> None:
        """
        Rebuild dropdown choices and hide blocked common questions
        selected in the other row.
        """
        blocked = blocked or set()
        current = self.choice.currentData()

        self.choice.blockSignals(True)
        self.choice.clear()

        self.choice.addItem("Select a question…", "")
        for question in COMMON_SECURITY_QUESTIONS:
            if question not in blocked or question == current:
                self.choice.addItem(question, question)
        self.choice.addItem("Custom question…", "__custom__")

        index = self.choice.findData(current)
        if index < 0:
            index = 0
        self.choice.setCurrentIndex(index)

        self.choice.blockSignals(False)
        self._selection_changed()

    def selected_common_question(self) -> str:
        data = self.choice.currentData()
        return data if data in COMMON_SECURITY_QUESTIONS else ""

    def question_text(self) -> str:
        value = self.choice.currentData()
        if value == "__custom__":
            return self.custom.text()
        return value or ""

    def value(self) -> SecurityQuestionAnswer:
        return SecurityQuestionAnswer(
            self.question_text(),
            self.answer.text(),
        )


class SecurityQuestionsPage(BasePage):
    def __init__(self):
        super().__init__(
            "Recovery questions",
            "Choose 2 different questions. Prefer answers that are not easy "
            "to discover online.",
        )

        self.first = SecurityQuestionRow(1)
        self.second = SecurityQuestionRow(2)

        self.root.addWidget(self.first)
        self.root.addSpacing(SPACE["md"])
        self.root.addWidget(self.second)
        self.root.addStretch()

        self.first.choice.currentIndexChanged.connect(self._sync_dropdowns)
        self.second.choice.currentIndexChanged.connect(self._sync_dropdowns)

        for row in (self.first, self.second):
            row.choice.currentIndexChanged.connect(self.error.clear_error)
            row.custom.textChanged.connect(self.error.clear_error)
            row.answer.edit.textChanged.connect(self.error.clear_error)

        self._sync_dropdowns()

    def _sync_dropdowns(self) -> None:
        """
        Prevent the same common question from being available in both dropdowns.
        Custom questions remain allowed, and validation still catches duplicates.
        """
        first_selected = self.first.selected_common_question()
        second_selected = self.second.selected_common_question()

        sender = self.sender()

        # If the user just selected a common question in one row,
        # remove it from the other row's dropdown.
        blocked_for_first = {second_selected} if second_selected else set()
        blocked_for_second = {first_selected} if first_selected else set()

        # Resolve edge case: if both somehow became the same common question,
        # clear the row the user did NOT just change.
        if first_selected and first_selected == second_selected:
            if sender is self.first.choice:
                self.second.choice.blockSignals(True)
                self.second.choice.setCurrentIndex(0)
                self.second.choice.blockSignals(False)
                second_selected = ""
                blocked_for_first = set()
                blocked_for_second = {first_selected}
            elif sender is self.second.choice:
                self.first.choice.blockSignals(True)
                self.first.choice.setCurrentIndex(0)
                self.first.choice.blockSignals(False)
                first_selected = ""
                blocked_for_first = {second_selected}
                blocked_for_second = set()

        self.first.rebuild_choices(blocked=blocked_for_first)
        self.second.rebuild_choices(blocked=blocked_for_second)

    def validatePage(self) -> bool:
        self.error.clear_error()

        try:
            self.wizard().capture_questions(
                [
                    self.first.value(),
                    self.second.value(),
                ]
            )
            return True
        except SecurityError as error:
            self.error.show_error(str(error))
            return False


class CurrencyPage(BasePage):
    def __init__(self):
        super().__init__(
            "Choose your currency",
            "This changes how amounts are displayed. "
            "It does not perform currency conversion.",
        )

        self.currency = QComboBox()
        for item in CURRENCIES:
            self.currency.addItem(item.label, item.code)

        self.root.addWidget(self.currency)
        self.root.addStretch()


class ThemePage(BasePage):
    def __init__(self):
        super().__init__(
            "Choose your theme",
            "The preview updates immediately. System follows the "
            "Windows appearance when available.",
        )

        self.light = QRadioButton("Light")
        self.dark = QRadioButton("Dark")
        self.system = QRadioButton("System")
        self.light.setChecked(True)

        self.root.addWidget(self.light)
        self.root.addWidget(self.dark)
        self.root.addWidget(self.system)

        self.preview = text_label("Selected theme: Light", "muted")
        self.root.addSpacing(SPACE["sm"])
        self.root.addWidget(self.preview)
        self.root.addStretch()

        self.light.toggled.connect(
            lambda checked: checked and self.wizard().preview_theme("light")
        )
        self.dark.toggled.connect(
            lambda checked: checked and self.wizard().preview_theme("dark")
        )
        self.system.toggled.connect(
            lambda checked: checked and self.wizard().preview_theme("system")
        )


class FinishPage(BasePage):
    def __init__(self):
        super().__init__(
            "Finish setup",
            "Review the choices below, then select Finish.",
        )

        self.summary = text_label("", "muted")
        self.root.addWidget(self.summary)
        self.root.addStretch()

    def initializePage(self) -> None:
        self.error.clear_error()

        wizard = self.wizard()
        self.summary.setText(
            f"Login method: {wizard.selected_login_method().upper()}\n"
            f"Currency: {wizard.currency_page.currency.currentData()}\n"
            f"Theme: {wizard.selected_theme().title()}\n"
            "Recovery questions: 2 configured"
        )

    def validatePage(self) -> bool:
        self.error.clear_error()

        try:
            return self.wizard().save_setup()
        except Exception:
            self.error.show_error(
                "ChitLog could not save the setup. "
                "No password or recovery answer was logged."
            )
            return False


class SetupWizard(QWizard):
    def __init__(self, assets: Path, service: SetupService):
        super().__init__()

        self.assets = assets
        self.service = service

        self._secret = ""
        self._confirmation = ""
        self._questions: list[SecurityQuestionAnswer] = []

        self.setWindowTitle(f"{APP_NAME} — First Run Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.resize(900, 680)
        self.setMinimumSize(780, 600)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)

        self.welcome_page = WelcomePage(assets)
        self.login_method_page = LoginMethodPage()
        self.credential_page = CredentialPage()
        self.security_page = SecurityQuestionsPage()
        self.currency_page = CurrencyPage()
        self.theme_page = ThemePage()
        self.finish_page = FinishPage()

        self._all_pages = (
            self.welcome_page,
            self.login_method_page,
            self.credential_page,
            self.security_page,
            self.currency_page,
            self.theme_page,
            self.finish_page,
        )

        for page in self._all_pages:
            self.addPage(page)

        self.preview_theme("light")

    def selected_login_method(self) -> str:
        return "pin" if self.login_method_page.pin.isChecked() else "password"

    def capture_secret(self, secret: str, confirmation: str) -> None:
        validate_secret(
            self.selected_login_method(),
            secret,
            confirmation,
        )
        self._secret = secret
        self._confirmation = confirmation

    def capture_questions(self, values: list[SecurityQuestionAnswer]) -> None:
        self._questions = validate_security_questions(values)

    def selected_theme(self) -> str:
        if self.theme_page.dark.isChecked():
            return "dark"
        if self.theme_page.system.isChecked():
            return "system"
        return "light"

    def _apply_wizard_theme_palette(self, theme_name: str) -> None:
        actual = resolve_theme(theme_name)
        theme = THEMES[actual]

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.background))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Base, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.field))
        palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Button, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(SCOOTER))

        self.setPalette(palette)

        for page in self._all_pages:
            page.apply_page_theme(theme_name)

    def preview_theme(self, theme: str) -> None:
        self.setStyleSheet(stylesheet(theme))
        self._apply_wizard_theme_palette(theme)

        effective = resolve_theme(theme)
        if theme == "system":
            self.theme_page.preview.setText(
                f"Selected theme: System (currently {effective.title()})"
            )
        else:
            self.theme_page.preview.setText(f"Selected theme: {theme.title()}")

        self.update()

    def save_setup(self) -> bool:
        self.service.complete_setup(
            SetupSubmission(
                login_method=self.selected_login_method(),
                secret=self._secret,
                confirmation=self._confirmation,
                security_questions=self._questions,
                currency_code=self.currency_page.currency.currentData(),
                theme=self.selected_theme(),
            )
        )
        return True