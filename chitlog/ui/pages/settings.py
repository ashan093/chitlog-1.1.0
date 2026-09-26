"""Step 20 completed Settings page."""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
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
from chitlog.core.update_decision import UpdateDisposition
from chitlog.services.settings_service import SettingsError, SettingsService
from chitlog.ui.pages.backup_settings import BackupSettingsCard
from chitlog.ui.pages.notifications import NotificationsPage
from chitlog.ui.theme import SPACE
from chitlog.ui.update_check_runner import (
    UpdateCheckFailure,
    UpdateCheckRunner,
    policy_from_preferences,
)
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
    worker_transaction_setting_changed = Signal(bool)
    liability_transaction_setting_changed = Signal(bool)
    update_preferences_changed = Signal()

    def __init__(
        self,
        settings_service: SettingsService,
        notification_service=None,
        backup_service=None,
        update_preferences_service=None,
        update_check_runner=None,
        parent=None,
    ):
        super().__init__(parent)
        self.settings_service = settings_service
        self.notification_service = notification_service
        self.backup_service = backup_service
        self.update_preferences_service = update_preferences_service
        self.update_check_runner = (
            update_check_runner
            if update_check_runner is not None
            else UpdateCheckRunner(self)
        )
        self.update_check_runner.succeeded.connect(
            self._manual_update_check_succeeded
        )
        self.update_check_runner.failed.connect(
            self._manual_update_check_failed
        )
        self.update_check_runner.finished.connect(
            self._manual_update_check_finished
        )

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
        # Updates
        # ---------------------------------------------------------------
        updates_card = Card("Updates")
        self._compact_card(updates_card)
        updates_card.body.addWidget(
            text_label(
                "Secure update checks use signed metadata only. "
                "Normal ChitLog accounting continues to work offline.",
                "muted",
            )
        )

        update_info = QFormLayout()
        update_info.setHorizontalSpacing(SPACE["md"])
        update_info.setVerticalSpacing(SPACE["xs"])
        self.update_current_version_label = QLabel(APP_VERSION)
        update_info.addRow("Current version", self.update_current_version_label)
        self.update_auto_check = QCheckBox("Automatically check for updates")
        self.update_auto_check.setToolTip(
            "When enabled, ChitLog may check the configured update service "
            "at the saved interval. Financial records are never sent."
        )
        update_info.addRow("Automatic checks", self.update_auto_check)
        self.update_channel_combo = QComboBox()
        self.update_channel_combo.addItem("Stable (recommended)", "stable")
        self.update_channel_combo.addItem("Beta", "beta")
        self.update_channel_combo.setMinimumWidth(190)
        update_info.addRow("Update channel", self.update_channel_combo)
        self.update_interval_label = QLabel("Every 24 hours")
        update_info.addRow("Check interval", self.update_interval_label)
        self.update_auto_install_label = QLabel("Off")
        self.update_auto_install_label.setToolTip(
            "Automatic installation is disabled. Updates are not installed "
            "without an explicit user action."
        )
        update_info.addRow("Automatic installation", self.update_auto_install_label)
        updates_card.body.addLayout(update_info)
        self.update_auto_check_notice = text_label("", "muted")
        self.update_auto_check_notice.setWordWrap(True)
        updates_card.body.addWidget(self.update_auto_check_notice)
        update_actions = QHBoxLayout()
        update_actions.setSpacing(SPACE["sm"])
        self.apply_update_preferences_button = button("Apply", "primary")
        self.apply_update_preferences_button.setEnabled(False)
        self.check_updates_button = button("Check for Updates")
        self.check_updates_button.setEnabled(False)
        self.check_updates_button.setToolTip(
            "Run one secure signed update check in the background. "
            "If the update service is unavailable, ChitLog continues "
            "working normally."
        )
        update_actions.addWidget(self.apply_update_preferences_button)
        update_actions.addWidget(self.check_updates_button)
        update_actions.addStretch(1)
        updates_card.body.addLayout(update_actions)
        self.update_preferences_feedback = text_label("", "muted")
        self.update_preferences_feedback.setVisible(False)
        updates_card.body.addWidget(self.update_preferences_feedback)
        root.addWidget(updates_card)

        # ---------------------------------------------------------------
        # Worker payments in Transactions
        # ---------------------------------------------------------------
        worker_expense_card = Card("Worker Payments")
        self._compact_card(worker_expense_card)
        self.worker_payments_in_transactions = QCheckBox(
            "Include worker payments and advances in Transactions → Expenses"
        )
        self.worker_payments_in_transactions.setToolTip(
            "When enabled, every worker payment or advance appears once as a linked expense. "
            "Turn this off to hide those linked expenses without deleting worker payment history."
        )
        worker_expense_row = QHBoxLayout()
        worker_expense_row.setSpacing(SPACE["sm"])
        worker_expense_row.addWidget(self.worker_payments_in_transactions, 1)
        self.apply_worker_expense_button = button("Apply", "primary")
        self.apply_worker_expense_button.setEnabled(False)
        worker_expense_row.addWidget(self.apply_worker_expense_button)
        worker_expense_card.body.addLayout(worker_expense_row)
        worker_expense_card.body.addWidget(
            text_label(
                "Default: On. Linked worker expenses are managed from Workers so they cannot be accidentally duplicated or edited separately.",
                "muted",
            )
        )
        self.worker_expense_feedback = text_label("", "muted")
        self.worker_expense_feedback.setVisible(False)
        worker_expense_card.body.addWidget(self.worker_expense_feedback)
        root.addWidget(worker_expense_card)

        # ---------------------------------------------------------------
        # Liability payments in Transactions
        # ---------------------------------------------------------------
        liability_expense_card = Card("Liability Payments")
        self._compact_card(liability_expense_card)
        self.liability_payments_in_transactions = QCheckBox(
            "Include liability payments in Transactions → Expenses"
        )
        self.liability_payments_in_transactions.setToolTip(
            "When enabled, each recorded liability payment appears once as a linked expense. "
            "Turn this off to hide those linked expenses without changing liability payment history."
        )
        liability_expense_row = QHBoxLayout()
        liability_expense_row.setSpacing(SPACE["sm"])
        liability_expense_row.addWidget(self.liability_payments_in_transactions, 1)
        self.apply_liability_expense_button = button("Apply", "primary")
        self.apply_liability_expense_button.setEnabled(False)
        liability_expense_row.addWidget(self.apply_liability_expense_button)
        liability_expense_card.body.addLayout(liability_expense_row)
        liability_expense_card.body.addWidget(
            text_label(
                "Default: On. Linked liability-payment expenses are managed from Liabilities and cannot be edited separately in Transactions.",
                "muted",
            )
        )
        self.liability_expense_feedback = text_label("", "muted")
        self.liability_expense_feedback.setVisible(False)
        liability_expense_card.body.addWidget(self.liability_expense_feedback)
        root.addWidget(liability_expense_card)

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
        self.update_auto_check.toggled.connect(self._update_preferences_controls_changed)
        self.update_channel_combo.currentIndexChanged.connect(self._update_preferences_controls_changed)
        self.apply_update_preferences_button.clicked.connect(self._apply_update_preferences)
        self.check_updates_button.clicked.connect(
            self._start_manual_update_check
        )
        self.save_credentials_button.clicked.connect(self._save_credentials)
        self.save_recovery_button.clicked.connect(self._save_recovery)
        self.show_secret_fields.toggled.connect(self._toggle_credentials)
        self.show_recovery_fields.toggled.connect(self._toggle_recovery)
        self.worker_payments_in_transactions.toggled.connect(
            self._worker_payments_transaction_toggled
        )
        self.apply_worker_expense_button.clicked.connect(
            self._apply_worker_payments_transaction_setting
        )
        self.liability_payments_in_transactions.toggled.connect(
            self._liability_payments_transaction_toggled
        )
        self.apply_liability_expense_button.clicked.connect(
            self._apply_liability_payments_transaction_setting
        )

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
        self._saved_worker_payments_in_transactions = bool(
            snapshot.worker_payments_in_transactions
        )
        self.worker_payments_in_transactions.blockSignals(True)
        self.worker_payments_in_transactions.setChecked(
            self._saved_worker_payments_in_transactions
        )
        self.worker_payments_in_transactions.blockSignals(False)
        self.apply_worker_expense_button.setEnabled(False)
        self._saved_liability_payments_in_transactions = bool(
            snapshot.liability_payments_in_transactions
        )
        self.liability_payments_in_transactions.blockSignals(True)
        self.liability_payments_in_transactions.setChecked(
            self._saved_liability_payments_in_transactions
        )
        self.liability_payments_in_transactions.blockSignals(False)
        self.apply_liability_expense_button.setEnabled(False)

        self._refresh_update_preferences()

        # Question text is not secret, so it can be shown. Stored answer hashes
        # can never be reversed, therefore answer fields intentionally stay blank.
        self.question_1.setText(snapshot.recovery_questions[0])
        self.question_2.setText(snapshot.recovery_questions[1])
        self.answer_1.clear()
        self.answer_2.clear()
        self.recovery_current_secret.clear()

        if self.notifications_page is not None and refresh_notifications:
            self.notifications_page.refresh()

    def _refresh_update_preferences(self) -> None:
        service = self.update_preferences_service
        if service is None:
            self.update_auto_check.setEnabled(False)
            self.update_channel_combo.setEnabled(False)
            self.apply_update_preferences_button.setEnabled(False)
            self.check_updates_button.setEnabled(False)
            self.update_preferences_feedback.setVisible(False)
            return
        snapshot = service.snapshot()
        self._saved_update_auto_check = bool(snapshot.auto_check_enabled)
        self._saved_update_channel = str(snapshot.channel)
        self.update_auto_check.blockSignals(True)
        self.update_auto_check.setChecked(self._saved_update_auto_check)
        self.update_auto_check.blockSignals(False)
        self.update_channel_combo.blockSignals(True)
        self._set_combo_value(self.update_channel_combo, self._saved_update_channel)
        self.update_channel_combo.blockSignals(False)
        hours = snapshot.check_interval_seconds / 3600
        self.update_interval_label.setText(
            f"Every {int(hours)} hours" if hours.is_integer()
            else f"Every {snapshot.check_interval_seconds} seconds"
        )
        self.update_auto_install_label.setText(
            "On" if snapshot.auto_install_enabled else "Off"
        )
        self._refresh_auto_check_notice(
            self._saved_update_auto_check,
            pending=False,
        )
        self.update_auto_check.setEnabled(True)
        self.update_channel_combo.setEnabled(True)
        self.apply_update_preferences_button.setEnabled(False)
        self.check_updates_button.setEnabled(
            not self.update_check_runner.running
        )

    def _refresh_auto_check_notice(
        self,
        enabled: bool,
        *,
        pending: bool,
    ) -> None:
        """Explain exactly what the Automatic checks preference means."""

        prefix = "After Apply: " if pending else ""
        if enabled:
            message = (
                f"{prefix}Automatic checks are on. ChitLog may contact the "
                "configured update service when the saved interval is due. "
                "Financial records are not sent."
            )
        else:
            message = (
                f"{prefix}Automatic checks are off. ChitLog will not contact "
                "the update service automatically, so it cannot know whether "
                "a newer version exists until you use Check for Updates "
                "manually."
            )

        self.update_auto_check_notice.setText(message)
        self.update_auto_check_notice.setVisible(True)

    def _update_preferences_controls_changed(self, *_args) -> None:
        if self.update_preferences_service is None:
            self.apply_update_preferences_button.setEnabled(False)
            return
        current_auto = self.update_auto_check.isChecked()
        current_channel = str(self.update_channel_combo.currentData() or "")
        changed = (
            current_auto != bool(getattr(self, "_saved_update_auto_check", current_auto))
            or current_channel != str(getattr(self, "_saved_update_channel", current_channel))
        )
        self.apply_update_preferences_button.setEnabled(changed)
        self.check_updates_button.setEnabled(
            not changed and not self.update_check_runner.running
        )
        self._refresh_auto_check_notice(
            current_auto,
            pending=changed,
        )
        if changed:
            self._show_feedback(
                self.update_preferences_feedback,
                "Unsaved update preference change — click Apply to save.",
            )
        else:
            self.update_preferences_feedback.setVisible(False)

    def _apply_update_preferences(self) -> None:
        service = self.update_preferences_service
        if service is None:
            return
        saved = service.configure(
            auto_check_enabled=self.update_auto_check.isChecked(),
            channel=str(self.update_channel_combo.currentData() or ""),
        )
        self._saved_update_auto_check = bool(saved.auto_check_enabled)
        self._saved_update_channel = str(saved.channel)
        self.apply_update_preferences_button.setEnabled(False)
        self.check_updates_button.setEnabled(
            not self.update_check_runner.running
        )
        state = "enabled" if saved.auto_check_enabled else "disabled"
        self._refresh_auto_check_notice(
            bool(saved.auto_check_enabled),
            pending=False,
        )
        self._show_feedback(
            self.update_preferences_feedback,
            f"Update preferences saved. Automatic checks are {state}; channel: {saved.channel}.",
        )
        self.update_preferences_changed.emit()

    def _start_manual_update_check(self) -> None:
        service = self.update_preferences_service
        if service is None or self.update_check_runner.running:
            return

        if self.apply_update_preferences_button.isEnabled():
            self._show_feedback(
                self.update_preferences_feedback,
                "Save update preference changes before checking.",
                error=True,
            )
            self.check_updates_button.setEnabled(False)
            return

        preferences = service.snapshot()
        policy = policy_from_preferences(preferences)

        self.check_updates_button.setEnabled(False)
        self._show_feedback(
            self.update_preferences_feedback,
            "Checking securely for updates…",
        )

        if not self.update_check_runner.start(policy):
            self._show_feedback(
                self.update_preferences_feedback,
                "An update check is already running.",
            )

    def _manual_update_check_succeeded(self, outcome) -> None:
        decision = outcome.decision

        if decision.disposition is UpdateDisposition.UP_TO_DATE:
            message = (
                f"ChitLog {decision.current_version} is up to date."
            )
        elif decision.disposition is UpdateDisposition.REQUIRED_UPDATE:
            message = (
                f"ChitLog {decision.available_version} is marked as a "
                "required update. The verified update notification in "
                "the main window has the available release actions."
            )
        else:
            message = (
                f"ChitLog {decision.available_version} is available. "
                "The verified update notification in the main window "
                "has the available release actions."
            )

        self._show_feedback(
            self.update_preferences_feedback,
            message,
        )

    def _manual_update_check_failed(
        self,
        failure: UpdateCheckFailure,
    ) -> None:
        messages = {
            "disabled": (
                "Update service is not configured yet. "
                "ChitLog remains fully usable offline."
            ),
            "network": (
                "Could not reach the update service. "
                "ChitLog remains fully usable offline."
            ),
            "security": (
                "Update information failed security verification and "
                "was rejected."
            ),
            "policy": (
                "Verified update information conflicted with local "
                "update policy and was rejected."
            ),
            "internal": (
                "The update check could not be completed."
            ),
        }
        self._show_feedback(
            self.update_preferences_feedback,
            messages.get(
                failure.kind,
                "The update check could not be completed.",
            ),
            error=failure.kind in {"security", "policy", "internal"},
        )

    def _manual_update_check_finished(self) -> None:
        changed = self.apply_update_preferences_button.isEnabled()
        self.check_updates_button.setEnabled(
            self.update_preferences_service is not None and not changed
        )

    def _worker_payments_transaction_toggled(self, checked: bool) -> None:
        saved = bool(getattr(self, "_saved_worker_payments_in_transactions", checked))
        changed = bool(checked) != saved
        self.apply_worker_expense_button.setEnabled(changed)
        if changed:
            self._show_feedback(
                self.worker_expense_feedback,
                "Unsaved change — click Apply to update worker-payment expense visibility.",
            )
        else:
            self.worker_expense_feedback.setVisible(False)

    def _confirm_worker_payment_transaction_change(self, enabled: bool) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Apply Worker Payment Setting")
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])
        layout.addWidget(text_label("Apply this setting?", "heading"))
        message = (
            "Worker payments and advances will appear in Transactions → Expenses. "
            "Existing linked worker expenses will become visible again, and future worker payments will be included automatically."
            if enabled
            else
            "Worker payments and advances will be hidden from Transactions → Expenses. "
            "Worker payment and advance history will remain unchanged in Workers."
        )
        layout.addWidget(text_label(message))
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = button("Cancel")
        apply_button = button("Apply", "primary")
        actions.addWidget(cancel)
        actions.addWidget(apply_button)
        layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject)
        apply_button.clicked.connect(dialog.accept)
        cancel.setDefault(True)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _apply_worker_payments_transaction_setting(self) -> None:
        checked = self.worker_payments_in_transactions.isChecked()
        saved = bool(getattr(self, "_saved_worker_payments_in_transactions", checked))
        if checked == saved:
            self.apply_worker_expense_button.setEnabled(False)
            return
        if not self._confirm_worker_payment_transaction_change(checked):
            self.worker_payments_in_transactions.blockSignals(True)
            self.worker_payments_in_transactions.setChecked(saved)
            self.worker_payments_in_transactions.blockSignals(False)
            self.apply_worker_expense_button.setEnabled(False)
            self._show_feedback(self.worker_expense_feedback, "Change cancelled. Setting was not modified.")
            return

        persisted = self.settings_service.set_worker_payments_in_transactions(checked)
        self._saved_worker_payments_in_transactions = bool(persisted)
        self.worker_payments_in_transactions.blockSignals(True)
        self.worker_payments_in_transactions.setChecked(bool(persisted))
        self.worker_payments_in_transactions.blockSignals(False)
        self.apply_worker_expense_button.setEnabled(False)
        message = (
            "Worker payments and advances will appear in Transactions as expenses."
            if persisted
            else "Worker payments and advances are hidden from Transactions. Worker records are unchanged."
        )
        self._show_feedback(self.worker_expense_feedback, message)
        self.worker_transaction_setting_changed.emit(bool(persisted))

    def _liability_payments_transaction_toggled(self, checked: bool) -> None:
        saved = bool(getattr(self, "_saved_liability_payments_in_transactions", checked))
        changed = bool(checked) != saved
        self.apply_liability_expense_button.setEnabled(changed)
        if changed:
            self._show_feedback(
                self.liability_expense_feedback,
                "Unsaved change — click Apply to update liability-payment expense visibility.",
            )
        else:
            self.liability_expense_feedback.setVisible(False)

    def _confirm_liability_payment_transaction_change(self, enabled: bool) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Apply Liability Payment Setting")
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        layout.setSpacing(SPACE["md"])
        layout.addWidget(text_label("Apply this setting?", "heading"))
        message = (
            "Liability payments will appear in Transactions → Expenses. "
            "Existing linked liability expenses will become visible again, and future liability payments will be included automatically."
            if enabled
            else
            "Liability payments will be hidden from Transactions → Expenses. "
            "Liability payment history will remain unchanged in Liabilities."
        )
        layout.addWidget(text_label(message))
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = button("Cancel")
        apply_button = button("Apply", "primary")
        actions.addWidget(cancel)
        actions.addWidget(apply_button)
        layout.addLayout(actions)
        cancel.clicked.connect(dialog.reject)
        apply_button.clicked.connect(dialog.accept)
        cancel.setDefault(True)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _apply_liability_payments_transaction_setting(self) -> None:
        checked = self.liability_payments_in_transactions.isChecked()
        saved = bool(getattr(self, "_saved_liability_payments_in_transactions", checked))
        if checked == saved:
            self.apply_liability_expense_button.setEnabled(False)
            return
        if not self._confirm_liability_payment_transaction_change(checked):
            self.liability_payments_in_transactions.blockSignals(True)
            self.liability_payments_in_transactions.setChecked(saved)
            self.liability_payments_in_transactions.blockSignals(False)
            self.apply_liability_expense_button.setEnabled(False)
            self._show_feedback(
                self.liability_expense_feedback,
                "Change cancelled. Setting was not modified.",
            )
            return

        persisted = self.settings_service.set_liability_payments_in_transactions(checked)
        self._saved_liability_payments_in_transactions = bool(persisted)
        self.liability_payments_in_transactions.blockSignals(True)
        self.liability_payments_in_transactions.setChecked(bool(persisted))
        self.liability_payments_in_transactions.blockSignals(False)
        self.apply_liability_expense_button.setEnabled(False)
        message = (
            "Liability payments will appear in Transactions as expenses."
            if persisted
            else "Liability payments are hidden from Transactions. Liability records are unchanged."
        )
        self._show_feedback(self.liability_expense_feedback, message)
        self.liability_transaction_setting_changed.emit(bool(persisted))

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
