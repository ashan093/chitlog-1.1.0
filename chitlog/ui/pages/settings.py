"""Step 20 completed Settings page."""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.config import APP_NAME, APP_VERSION
from chitlog.core.security import SecurityQuestionAnswer
from chitlog.services.settings_service import SettingsError, SettingsService
from chitlog.ui.pages.backup_settings import BackupSettingsCard
from chitlog.ui.pages.notifications import NotificationsPage
from chitlog.ui.theme import SPACE
from chitlog.ui.widgets import Card, button, text_label


COMMON_SECURITY_QUESTIONS = (
    "What was the name of your first school?",
    "What was the name of your first pet?",
    "What was your childhood nickname?",
    "What is the name of a memorable place from your childhood?",
    "What was the title of a book or movie you strongly remember?",
    "What private phrase can you reliably remember?",
)


class SecurityQuestionPicker(QWidget):
    """Compact predefined security-question dropdown with Custom fallback.

    setText()/text()/maxLength() intentionally mirror the small QLineEdit API
    the earlier Settings page exposed, preserving older tests and call sites.
    """

    CUSTOM_VALUE = "__custom__"

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["xs"])

        self.choice = QComboBox()
        self.choice.addItem("Select a question…", "")
        for question in COMMON_SECURITY_QUESTIONS:
            self.choice.addItem(question, question)
        self.choice.addItem("Custom question…", self.CUSTOM_VALUE)
        self.choice.setMinimumWidth(280)
        layout.addWidget(self.choice)

        self.custom = QLineEdit()
        self.custom.setPlaceholderText("Type your custom security question")
        self.custom.setMaxLength(120)
        self.custom.setVisible(False)
        layout.addWidget(self.custom)

        self.choice.currentIndexChanged.connect(self._selection_changed)

    def _selection_changed(self, *_args) -> None:
        custom_selected = self.choice.currentData() == self.CUSTOM_VALUE
        self.custom.setVisible(custom_selected)
        if custom_selected and self.isVisible():
            self.custom.setFocus()

    def text(self) -> str:
        value = self.choice.currentData()
        if value == self.CUSTOM_VALUE:
            return self.custom.text()
        return str(value or "")

    def setText(self, value: str) -> None:
        value = " ".join((value or "").strip().split())
        if not value:
            self.choice.setCurrentIndex(0)
            self.custom.clear()
            self.custom.setVisible(False)
            return

        index = self.choice.findData(value)
        if index >= 0:
            self.choice.setCurrentIndex(index)
            self.custom.clear()
            self.custom.setVisible(False)
            return

        custom_index = self.choice.findData(self.CUSTOM_VALUE)
        self.choice.setCurrentIndex(custom_index)
        self.custom.setText(value)
        self.custom.setVisible(True)

    def maxLength(self) -> int:
        return self.custom.maxLength()



class SettingsPage(QWidget):
    """One place for all V1 settings required by the master plan."""

    theme_requested = Signal(str)
    notification_settings_changed = Signal()
    notification_test_requested = Signal()
    restore_completed = Signal()

    def __init__(
        self,
        settings_service: SettingsService,
        notification_service=None,
        backup_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self.settings_service = settings_service
        self.notification_service = notification_service
        self.backup_service = backup_service

        self.setObjectName("settingsPage")
        # Settings is intentionally denser than transaction-entry screens.
        # Keep the global theme colors/focus states, but reduce only local
        # typography, padding, and control height.
        self.setStyleSheet(
            """
            QWidget#settingsPage QLabel { font-size: 13px; }
            QWidget#settingsPage QLabel[role="title"] {
                font-size: 20px; font-weight: 700;
            }
            QWidget#settingsPage QLabel[role="heading"] {
                font-size: 16px; font-weight: 650;
            }
            QWidget#settingsPage QLabel[role="muted"] { font-size: 12px; }
            QWidget#settingsPage QLabel[role="eyebrow"] { font-size: 11px; }
            QWidget#settingsPage QLabel[role="error"] { font-size: 12px; }
            QWidget#settingsPage QLineEdit,
            QWidget#settingsPage QComboBox {
                padding: 5px 7px;
                min-height: 18px;
                font-size: 13px;
            }
            QWidget#settingsPage QPushButton {
                padding: 6px 10px;
                min-height: 18px;
                font-size: 13px;
            }
            QWidget#settingsPage QCheckBox {
                padding: 2px 1px;
                spacing: 6px;
                font-size: 13px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["sm"])
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        intro = QVBoxLayout()
        intro.setSpacing(SPACE["xs"])
        intro.addWidget(text_label("SETTINGS", "eyebrow"))
        intro.addWidget(text_label("ChitLog settings", "heading"))
        root.addLayout(intro)

        # ---------------------------------------------------------------
        # Currency
        # ---------------------------------------------------------------
        currency_card = Card("Currency")
        self._compact_card(currency_card)
        currency_card.body.addWidget(
            text_label(
                "Display/input currency only — no exchange-rate conversion.",
                "muted",
            )
        )
        currency_row = QHBoxLayout()
        currency_row.setSpacing(SPACE["sm"])
        self.currency_combo = QComboBox()
        for option in self.settings_service.currencies:
            self.currency_combo.addItem(option.label, option.code)
        self.currency_combo.setMinimumWidth(220)
        self.save_currency_button = button("Save Currency", "primary")
        currency_row.addWidget(self.currency_combo)
        currency_row.addWidget(self.save_currency_button)
        currency_row.addStretch(1)
        currency_card.body.addLayout(currency_row)

        self.currency_feedback = text_label("", "muted")
        self.currency_feedback.setVisible(False)
        currency_card.body.addWidget(self.currency_feedback)

        precision_note = QLabel(
            "Precision-changing currencies (for example JPY) are blocked after "
            "financial records exist, protecting stored money values."
        )
        precision_note.setProperty("role", "muted")
        precision_note.setWordWrap(True)
        currency_card.body.addWidget(precision_note)
        root.addWidget(currency_card)

        # ---------------------------------------------------------------
        # Appearance
        # ---------------------------------------------------------------
        appearance_card = Card("Appearance")
        self._compact_card(appearance_card)
        appearance_card.body.addWidget(
            text_label(
                "Light, Dark, or System. Applies immediately.",
                "muted",
            )
        )
        appearance_row = QHBoxLayout()
        appearance_row.setSpacing(SPACE["sm"])
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("System", "system")
        self.theme_combo.setMinimumWidth(150)
        self.save_theme_button = button("Apply Appearance", "primary")
        appearance_row.addWidget(self.theme_combo)
        appearance_row.addWidget(self.save_theme_button)
        appearance_row.addStretch(1)
        appearance_card.body.addLayout(appearance_row)
        root.addWidget(appearance_card)

        # ---------------------------------------------------------------
        # Security — compact two-column layout
        # ---------------------------------------------------------------
        security_card = Card("Security")
        self._compact_card(security_card)
        security_card.body.addWidget(
            text_label(
                "Current PIN/password is required for security changes. "
                "Plaintext secrets are never stored.",
                "muted",
            )
        )

        security_columns = QHBoxLayout()
        security_columns.setContentsMargins(0, 0, 0, 0)
        security_columns.setSpacing(SPACE["md"])

        # Login credential column.
        credential_panel = QFrame()
        credential_panel.setProperty("role", "settingsSubPanel")
        credential_layout = QVBoxLayout(credential_panel)
        credential_layout.setContentsMargins(0, 0, 0, 0)
        credential_layout.setSpacing(SPACE["xs"])
        credential_layout.addWidget(text_label("LOGIN", "eyebrow"))

        self.login_method_label = text_label("", "muted")
        credential_layout.addWidget(self.login_method_label)

        credential_form = QFormLayout()
        credential_form.setHorizontalSpacing(SPACE["sm"])
        credential_form.setVerticalSpacing(SPACE["xs"])
        credential_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.current_secret_edit = QLineEdit()
        self.current_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_secret_edit.setMaxLength(128)
        credential_form.addRow("Current", self.current_secret_edit)

        self.login_method_combo = QComboBox()
        self.login_method_combo.addItem("PIN", "pin")
        self.login_method_combo.addItem("Password", "password")
        credential_form.addRow("New method", self.login_method_combo)

        self.new_secret_edit = QLineEdit()
        self.new_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_secret_edit.setMaxLength(128)
        credential_form.addRow("New secret", self.new_secret_edit)

        self.confirm_secret_edit = QLineEdit()
        self.confirm_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_secret_edit.setMaxLength(128)
        credential_form.addRow("Confirm", self.confirm_secret_edit)
        credential_layout.addLayout(credential_form)

        self.show_secret_fields = QCheckBox("Show fields")
        credential_layout.addWidget(self.show_secret_fields)

        self.save_credentials_button = button("Change Login", "primary")
        self.save_credentials_button.setToolTip("Change Login Credentials")
        credential_layout.addWidget(
            self.save_credentials_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        credential_layout.addStretch(1)

        # Recovery column.
        recovery_panel = QFrame()
        recovery_panel.setProperty("role", "settingsSubPanel")
        recovery_layout = QVBoxLayout(recovery_panel)
        recovery_layout.setContentsMargins(0, 0, 0, 0)
        recovery_layout.setSpacing(SPACE["xs"])
        recovery_layout.addWidget(text_label("RECOVERY", "eyebrow"))
        recovery_layout.addWidget(
            text_label("Choose two different questions, or select Custom.", "muted")
        )

        recovery_form = QFormLayout()
        recovery_form.setHorizontalSpacing(SPACE["sm"])
        recovery_form.setVerticalSpacing(SPACE["xs"])
        recovery_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.recovery_current_secret = QLineEdit()
        self.recovery_current_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.recovery_current_secret.setMaxLength(128)
        recovery_form.addRow("Current", self.recovery_current_secret)

        self.question_1 = SecurityQuestionPicker()
        self.answer_1 = QLineEdit()
        self.answer_1.setEchoMode(QLineEdit.EchoMode.Password)
        self.answer_1.setMaxLength(200)

        self.question_2 = SecurityQuestionPicker()
        self.answer_2 = QLineEdit()
        self.answer_2.setEchoMode(QLineEdit.EchoMode.Password)
        self.answer_2.setMaxLength(200)

        recovery_form.addRow("Question 1", self.question_1)
        recovery_form.addRow("Answer 1", self.answer_1)
        recovery_form.addRow("Question 2", self.question_2)
        recovery_form.addRow("Answer 2", self.answer_2)
        recovery_layout.addLayout(recovery_form)

        self.show_recovery_fields = QCheckBox("Show answers")
        recovery_layout.addWidget(self.show_recovery_fields)

        self.save_recovery_button = button("Update Recovery", "primary")
        self.save_recovery_button.setToolTip("Update Recovery Questions")
        recovery_layout.addWidget(
            self.save_recovery_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )

        security_columns.addWidget(credential_panel, 1)
        security_columns.addWidget(recovery_panel, 1)
        security_card.body.addLayout(security_columns)

        self.security_feedback = text_label("", "muted")
        self.security_feedback.setVisible(False)
        security_card.body.addWidget(self.security_feedback)
        root.addWidget(security_card)

        # ---------------------------------------------------------------
        # Notifications (existing reliable Step 17 implementation)
        # ---------------------------------------------------------------
        self.notifications_page = None
        if self.notification_service is not None:
            self.notifications_page = NotificationsPage(
                self.notification_service,
                backup_service=None,
                embedded=True,
                parent=self,
            )
            self.notifications_page.settings_changed.connect(
                self.notification_settings_changed.emit
            )
            self.notifications_page.test_requested.connect(
                self.notification_test_requested.emit
            )
            root.addWidget(self.notifications_page)

        # ---------------------------------------------------------------
        # Data-only local backup (confirmed Step 18)
        # ---------------------------------------------------------------
        self.backup_card = None
        if self.backup_service is not None:
            self.backup_card = BackupSettingsCard(self.backup_service, self, compact=True)
            self.backup_card.restore_completed.connect(
                self.restore_completed.emit
            )
            root.addWidget(self.backup_card)

        # ---------------------------------------------------------------
        # Application information
        # ---------------------------------------------------------------
        info = Card("Application Information")
        self._compact_card(info)
        info_grid = QFormLayout()
        info_grid.setHorizontalSpacing(SPACE["md"])
        info_grid.setVerticalSpacing(SPACE["xs"])
        info_grid.addRow("Application", QLabel(APP_NAME))
        info_grid.addRow("Version", QLabel(APP_VERSION))
        info_grid.addRow("Developed by", QLabel("Ashan Madusanka"))
        info_grid.addRow(
            "Copyright",
            QLabel("© 2026 Ashan Madusanka. All rights reserved."),
        )
        info_grid.addRow("License", QLabel("Proprietary"))
        info_grid.addRow("Data storage", QLabel("Local encrypted SQLCipher database"))
        info_grid.addRow("Database key", QLabel("Windows Credential Manager"))
        info_grid.addRow("Portable backup", QLabel("Encrypted data-only .chitdata"))
        info_grid.addRow("Cloud backup", QLabel("Not included in this version"))
        info_grid.addRow("Telemetry", QLabel("None by default"))
        info_grid.addRow("Normal accounting", QLabel("Works offline"))
        info.body.addLayout(info_grid)

        privacy = QLabel(
            "ChitLog is designed as a local/private personal finance application. "
            "Financial records are not sent to analytics services."
        )
        privacy.setProperty("role", "muted")
        privacy.setWordWrap(True)
        info.body.addWidget(privacy)
        root.addWidget(info)

        self.save_currency_button.clicked.connect(self._save_currency)
        self.save_theme_button.clicked.connect(self._save_theme)
        self.save_credentials_button.clicked.connect(self._save_credentials)
        self.save_recovery_button.clicked.connect(self._save_recovery)
        self.show_secret_fields.toggled.connect(self._toggle_credentials)
        self.show_recovery_fields.toggled.connect(self._toggle_recovery)

        self.refresh(refresh_notifications=False)

    @staticmethod
    def _compact_card(card: Card) -> None:
        card.body.setContentsMargins(14, 12, 14, 12)
        card.body.setSpacing(SPACE["sm"])

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _show_feedback(label: QLabel, message: str, *, error: bool = False) -> None:
        label.setProperty("role", "error" if error else "muted")
        label.setText(message)
        label.setVisible(True)
        label.style().unpolish(label)
        label.style().polish(label)

    def _toggle_credentials(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        for field in (
            self.current_secret_edit,
            self.new_secret_edit,
            self.confirm_secret_edit,
        ):
            field.setEchoMode(mode)

    def _toggle_recovery(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.recovery_current_secret.setEchoMode(mode)
        self.answer_1.setEchoMode(mode)
        self.answer_2.setEchoMode(mode)

    def refresh(self, *, refresh_notifications: bool = True) -> None:
        snapshot = self.settings_service.snapshot()
        self._set_combo_value(self.currency_combo, snapshot.currency_code)
        self._set_combo_value(self.theme_combo, snapshot.theme)
        self._set_combo_value(self.login_method_combo, snapshot.login_method)
        self.login_method_label.setText(
            f"Current login method: {snapshot.login_method.title()}"
        )

        # Question text is not secret, so it can be shown. Stored answer hashes
        # can never be reversed, therefore answer fields intentionally stay blank.
        self.question_1.setText(snapshot.recovery_questions[0])
        self.question_2.setText(snapshot.recovery_questions[1])
        self.answer_1.clear()
        self.answer_2.clear()
        self.recovery_current_secret.clear()

        if self.notifications_page is not None and refresh_notifications:
            self.notifications_page.refresh()

    def _save_currency(self) -> None:
        code = str(self.currency_combo.currentData() or "")
        try:
            currency = self.settings_service.change_currency(code)
        except SettingsError as error:
            self._show_feedback(self.currency_feedback, str(error), error=True)
            return

        self._show_feedback(
            self.currency_feedback,
            f"Currency saved as {currency.code} ({currency.symbol}). "
            "Close and reopen ChitLog to apply it to every finance view. "
            "Existing amounts are not exchange-rate converted.",
        )

    def _save_theme(self) -> None:
        theme = str(self.theme_combo.currentData() or "")
        if theme not in self.settings_service.themes:
            return
        self.theme_requested.emit(theme)

    def _save_credentials(self) -> None:
        method = str(self.login_method_combo.currentData() or "")
        try:
            saved_method = self.settings_service.change_credentials(
                current_secret=self.current_secret_edit.text(),
                login_method=method,
                new_secret=self.new_secret_edit.text(),
                confirmation=self.confirm_secret_edit.text(),
            )
        except SettingsError as error:
            self._show_feedback(self.security_feedback, str(error), error=True)
            return

        self.current_secret_edit.clear()
        self.new_secret_edit.clear()
        self.confirm_secret_edit.clear()
        self.show_secret_fields.setChecked(False)
        self.login_method_label.setText(
            f"Current login method: {saved_method.title()}"
        )
        self._show_feedback(
            self.security_feedback,
            f"Login credentials updated. Future logins will use {saved_method.title()}.",
        )

    def _save_recovery(self) -> None:
        questions = [
            SecurityQuestionAnswer(
                self.question_1.text(),
                self.answer_1.text(),
            ),
            SecurityQuestionAnswer(
                self.question_2.text(),
                self.answer_2.text(),
            ),
        ]
        try:
            saved = self.settings_service.change_recovery_questions(
                current_secret=self.recovery_current_secret.text(),
                questions=questions,
            )
        except SettingsError as error:
            self._show_feedback(self.security_feedback, str(error), error=True)
            return

        self.question_1.setText(saved[0])
        self.question_2.setText(saved[1])
        self.answer_1.clear()
        self.answer_2.clear()
        self.recovery_current_secret.clear()
        self.show_recovery_fields.setChecked(False)
        self._show_feedback(
            self.security_feedback,
            "Recovery questions updated securely. Plaintext answers were not stored.",
        )
