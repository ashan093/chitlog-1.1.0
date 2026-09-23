"""Step 18 encrypted business-data-only backup/restore controls."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from chitlog.services.backup_service import BackupError, BackupPasswordError, BackupService
from chitlog.ui.theme import SPACE
from chitlog.ui.widgets import Card, button, text_label


class BackupPasswordDialog(QDialog):
    def __init__(self, *, creating: bool, parent=None):
        super().__init__(parent)
        self.creating = creating
        self.setWindowTitle("Data Backup Password")
        self.setModal(True)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        root.setSpacing(SPACE["md"])
        root.addWidget(
            text_label(
                "Create data-backup password" if creating else "Enter data-backup password",
                "heading",
            )
        )
        root.addWidget(
            text_label(
                "This separate password protects the portable data backup. "
                "Your ChitLog login password/PIN is never copied into the backup.",
                "muted",
            )
        )

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(
            "At least 12 characters" if creating else "Data-backup password"
        )
        root.addWidget(self.password_edit)

        self.confirm_edit = None
        if creating:
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_edit.setPlaceholderText("Confirm data-backup password")
            root.addWidget(self.confirm_edit)

        self.show_password = QCheckBox("Show password")
        root.addWidget(self.show_password)

        self.error = text_label("", "error")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        root.addWidget(self.error)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = button("Cancel")
        accept = button("Continue", "primary")
        actions.addWidget(cancel)
        actions.addWidget(accept)
        root.addLayout(actions)

        self.show_password.toggled.connect(self._toggle_visibility)
        cancel.clicked.connect(self.reject)
        accept.clicked.connect(self._accept_if_valid)
        self.password_edit.returnPressed.connect(self._accept_if_valid)
        if self.confirm_edit is not None:
            self.confirm_edit.returnPressed.connect(self._accept_if_valid)

    def _toggle_visibility(self, shown: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(mode)
        if self.confirm_edit is not None:
            self.confirm_edit.setEchoMode(mode)

    def _accept_if_valid(self) -> None:
        password = self.password_edit.text()
        if self.creating:
            if len(password) < 12:
                self.error.setText("Use at least 12 characters for the data-backup password.")
                self.error.setVisible(True)
                return
            if self.confirm_edit is None or password != self.confirm_edit.text():
                self.error.setText("Data-backup passwords do not match.")
                self.error.setVisible(True)
                return
        elif not password:
            self.error.setText("Enter the data-backup password.")
            self.error.setVisible(True)
            return
        self.accept()

    def password(self) -> str:
        return self.password_edit.text()


def _confirm_restore(parent) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Restore ChitLog Data")
    dialog.setModal(True)
    dialog.setMinimumWidth(540)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    root.setSpacing(SPACE["md"])
    root.addWidget(text_label("Replace current business data?", "heading"))

    warning = QLabel(
        "This restore replaces ChitLog business records from the selected data backup: "
        "transactions and categories, budgets, liabilities and payments, workers, "
        "work records, attendance, worker payments/advances, and payroll carry-forward data.\n\n"
        "Your current ChitLog login/PIN/password, recovery questions, currency/theme, "
        "notification preferences, and other application settings are NOT restored or changed.\n\n"
        "ChitLog creates an encrypted local safety snapshot before changing the data."
    )
    warning.setWordWrap(True)
    root.addWidget(warning)

    actions = QHBoxLayout()
    actions.addStretch(1)
    cancel = button("Cancel")
    restore = button("Restore Data Backup")
    restore.setProperty("role", "danger")
    actions.addWidget(cancel)
    actions.addWidget(restore)
    root.addLayout(actions)

    cancel.clicked.connect(dialog.reject)
    restore.clicked.connect(dialog.accept)
    return dialog.exec() == QDialog.DialogCode.Accepted


def _show_restore_complete(parent) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Data Restore Complete")
    dialog.setModal(True)
    dialog.setMinimumWidth(540)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
    root.setSpacing(SPACE["md"])

    root.addWidget(text_label("Business data restored successfully", "heading"))

    message = QLabel(
        "The data backup has been restored and verified successfully.\n\n"
        "Your existing ChitLog login credentials, security questions, theme, currency, "
        "notification settings, and other application settings were kept unchanged.\n\n"
        "ChitLog will close only after you click the button below so every data page "
        "can reload cleanly when you open it again."
    )
    message.setWordWrap(True)
    root.addWidget(message)

    actions = QHBoxLayout()
    actions.addStretch(1)
    close_button = button("Close ChitLog", "primary")
    actions.addWidget(close_button)
    root.addLayout(actions)

    close_button.clicked.connect(dialog.accept)
    dialog.exec()


class BackupSettingsCard(QWidget):
    restore_completed = Signal()

    def __init__(self, service: BackupService, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.service = service
        self.compact = bool(compact)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = Card("Data Backup & Restore")
        if self.compact:
            card.body.setContentsMargins(14, 12, 14, 12)
            card.body.setSpacing(SPACE["sm"])
        else:
            card.body.setSpacing(SPACE["md"])
        card.body.addWidget(
            text_label(
                "Encrypted .chitdata business-data backup. Login/recovery/settings are excluded."
                if self.compact
                else "Create a portable encrypted backup of ChitLog business data only.",
                "muted",
            )
        )

        included = QLabel(
            "Included: transactions/categories, budgets, liabilities/payments, "
            "workers, work records/attendance, worker payments/advances, and payroll carry-forward."
        )
        included.setProperty("role", "muted")
        included.setWordWrap(True)
        included.setVisible(not self.compact)
        card.body.addWidget(included)

        excluded = QLabel(
            "Not included: ChitLog login/PIN/password, security-question answers, "
            "theme, currency, notification preferences, or other application settings."
        )
        excluded.setProperty("role", "muted")
        excluded.setWordWrap(True)
        excluded.setVisible(not self.compact)
        card.body.addWidget(excluded)

        format_note = QLabel(
            "Data backups use the .chitdata format and are protected by a separate backup password."
        )
        format_note.setProperty("role", "muted")
        format_note.setWordWrap(True)
        format_note.setVisible(not self.compact)
        card.body.addWidget(format_note)

        actions = QHBoxLayout()
        actions.setSpacing(SPACE["sm"])
        self.create_button = button("Create Data Backup", "primary")
        self.restore_button = button("Restore Data Backup")
        actions.addWidget(self.create_button)
        actions.addWidget(self.restore_button)
        actions.addStretch(1)
        card.body.addLayout(actions)

        self.feedback = text_label("", "muted")
        self.feedback.setWordWrap(True)
        self.feedback.setVisible(False)
        card.body.addWidget(self.feedback)

        safety = text_label(
            "Before a data restore, ChitLog keeps a full encrypted local safety snapshot "
            "for rollback. That safety snapshot is internal and is not a portable data backup.",
            "muted",
        )
        safety.setWordWrap(True)
        if self.compact:
            safety.setText(
                "Restore creates an encrypted local safety snapshot first."
            )
        card.body.addWidget(safety)
        root.addWidget(card)

        self.create_button.clicked.connect(self.create_backup)
        self.restore_button.clicked.connect(self.restore_backup)

    def _show_feedback(self, message: str, *, error: bool = False) -> None:
        self.feedback.setProperty("role", "error" if error else "muted")
        self.feedback.setText(message)
        self.feedback.setVisible(True)
        self.feedback.style().unpolish(self.feedback)
        self.feedback.style().polish(self.feedback)

    def create_backup(self) -> None:
        password_dialog = BackupPasswordDialog(creating=True, parent=self)
        if password_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        default_path = self.service.local_backup_dir / self.service.suggested_filename()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Create ChitLog Data Backup",
            str(default_path),
            "ChitLog Data Backup (*.chitdata)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".chitdata":
            destination = destination.with_suffix(".chitdata")

        try:
            saved = self.service.create_backup(destination, password_dialog.password())
        except BackupError as error:
            self._show_feedback(str(error), error=True)
            return
        self._show_feedback(f"Data backup completed: {saved.name}")

    def restore_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ChitLog Data Backup",
            str(self.service.local_backup_dir),
            "ChitLog Data Backup (*.chitdata)",
        )
        if not path:
            return
        if not _confirm_restore(self):
            return

        password_dialog = BackupPasswordDialog(creating=False, parent=self)
        if password_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self.service.restore_backup(Path(path), password_dialog.password())
        except BackupPasswordError as error:
            self._show_feedback(str(error), error=True)
            return
        except BackupError as error:
            self._show_feedback(str(error), error=True)
            return

        self._show_feedback(
            "Business data restored safely. Login and application settings were kept unchanged."
        )
        self.create_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        _show_restore_complete(self)
        self.restore_completed.emit()
