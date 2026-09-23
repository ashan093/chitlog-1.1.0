"""Reusable local desktop reminder controls used by Settings."""
from __future__ import annotations

from PySide6.QtCore import QTime, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chitlog.services.notification_service import (
    NotificationError,
    NotificationService,
)
from chitlog.ui.theme import SPACE
from chitlog.ui.pages.backup_settings import BackupSettingsCard
from chitlog.ui.widgets import Card, button, text_label


class NotificationsPage(QWidget):
    """Reusable notification controls for the completed Settings page."""

    settings_changed = Signal()
    test_requested = Signal()

    def __init__(
        self,
        service: NotificationService,
        backup_service=None,
        embedded: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.backup_service = backup_service
        self.embedded = bool(embedded)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["md"])
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        if not self.embedded:
            intro = QVBoxLayout()
            intro.setSpacing(SPACE["xs"])
            intro.addWidget(text_label("NOTIFICATIONS", "eyebrow"))
            intro.addWidget(text_label("Daily desktop reminder", "title"))
            intro.addWidget(
                text_label(
                    "A private local reminder to update ChitLog. On Windows, you can also keep the reminder active after the main ChitLog window is closed.",
                    "muted",
                )
            )
            root.addLayout(intro)

        card = Card("Notifications" if self.embedded else "Daily Reminder")
        if self.embedded:
            card.body.setContentsMargins(14, 12, 14, 12)
            card.body.setSpacing(SPACE["sm"])
        else:
            card.body.setSpacing(SPACE["md"])

        self.enabled_checkbox = QCheckBox("Enable daily desktop reminder")
        self.enabled_checkbox.setAccessibleName("Enable daily desktop reminder")
        card.body.addWidget(self.enabled_checkbox)

        self.background_checkbox = QCheckBox(
            "Notify even when ChitLog is closed"
        )
        self.background_checkbox.setAccessibleName(
            "Notify even when ChitLog is closed"
        )
        self.background_checkbox.setToolTip(
            "Uses Windows Task Scheduler. The reminder can run while you are signed in even if the main ChitLog window is closed."
        )
        card.body.addWidget(self.background_checkbox)

        self.background_note = QLabel(
            "Uses Windows Task Scheduler; the full ChitLog window does not stay running."
            if self.embedded
            else "Closed-app reminders use Windows Task Scheduler and do not keep the full ChitLog window running."
        )
        self.background_note.setProperty("role", "muted")
        self.background_note.setWordWrap(True)
        card.body.addWidget(self.background_note)

        time_row = QHBoxLayout()
        time_row.setSpacing(SPACE["sm"])
        time_row.addWidget(text_label("Reminder time", "muted"))
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setProperty("compact", True)
        self.time_edit.setFixedWidth(78)
        self.time_edit.setFixedHeight(34)
        self.time_edit.setAccessibleName("Daily reminder time")
        # Windows' native QTimeEdit arrows can disappear after custom dark
        # theming. Use explicit ChitLog-themed buttons instead so the controls
        # remain visible in Light, Dark, and System modes.
        self.time_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        time_row.addWidget(self.time_edit)

        time_buttons = QVBoxLayout()
        time_buttons.setContentsMargins(0, 0, 0, 0)
        time_buttons.setSpacing(1)

        self.time_up_button = QToolButton()
        self.time_up_button.setText("▴")
        self.time_up_button.setProperty("timeStepper", True)
        self.time_up_button.setFixedSize(20, 14)
        self.time_up_button.setToolTip("Increase reminder time by 1 minute")
        self.time_up_button.setAccessibleName("Increase reminder time")

        self.time_down_button = QToolButton()
        self.time_down_button.setText("▾")
        self.time_down_button.setProperty("timeStepper", True)
        self.time_down_button.setFixedSize(20, 14)
        self.time_down_button.setToolTip("Decrease reminder time by 1 minute")
        self.time_down_button.setAccessibleName("Decrease reminder time")

        time_buttons.addWidget(self.time_up_button)
        time_buttons.addWidget(self.time_down_button)
        time_row.addLayout(time_buttons)
        time_row.addStretch(1)
        card.body.addLayout(time_row)

        self.privacy_note = QLabel(
            "Reminder text is generic and contains no financial details."
            if self.embedded
            else "The reminder text is generic and contains no balances, transaction amounts, worker names, or other financial details."
        )
        self.privacy_note.setProperty("role", "muted")
        self.privacy_note.setWordWrap(True)
        card.body.addWidget(self.privacy_note)

        actions = QHBoxLayout()
        actions.setSpacing(SPACE["sm"])
        self.save_button = button("Save Reminder Settings", "primary")
        self.test_button = button("Test Reminder")
        actions.addWidget(self.save_button)
        actions.addWidget(self.test_button)
        actions.addStretch(1)
        card.body.addLayout(actions)

        self.feedback = text_label("", "muted")
        self.feedback.setWordWrap(True)
        self.feedback.setVisible(False)
        card.body.addWidget(self.feedback)

        root.addWidget(card)

        if not self.embedded:
            online_note = Card("Email Reminder")
            online_note.body.addWidget(
                text_label(
                    "Not enabled in Step 17. Email is an optional online feature and will only be added later with secure credential handling.",
                    "muted",
                )
            )
            root.addWidget(online_note)

        self.backup_card = None
        if self.backup_service is not None:
            self.backup_card = BackupSettingsCard(self.backup_service, self)
            root.addWidget(self.backup_card)

        self.save_button.clicked.connect(self.save)
        self.test_button.clicked.connect(self.test_requested.emit)
        self.time_up_button.clicked.connect(self._increase_time)
        self.time_down_button.clicked.connect(self._decrease_time)
        self.enabled_checkbox.toggled.connect(self._update_enabled_hint)
        self.refresh()

    def _increase_time(self) -> None:
        self.time_edit.setTime(self.time_edit.time().addSecs(60))

    def _decrease_time(self) -> None:
        self.time_edit.setTime(self.time_edit.time().addSecs(-60))

    def _show_feedback(self, text: str) -> None:
        self.feedback.setText(text)
        self.feedback.setVisible(True)

    def _update_enabled_hint(self, enabled: bool) -> None:
        self.time_edit.setEnabled(True)
        self.background_checkbox.setEnabled(
            bool(enabled and self.service.background_supported)
        )
        if not enabled:
            self.background_checkbox.setChecked(False)
        self.save_button.setText("Save Reminder Settings")

    def refresh(self) -> None:
        settings = self.service.settings()
        self.enabled_checkbox.blockSignals(True)
        self.enabled_checkbox.setChecked(settings.enabled)
        self.enabled_checkbox.blockSignals(False)

        self.background_checkbox.blockSignals(True)
        self.background_checkbox.setChecked(settings.background_enabled)
        self.background_checkbox.blockSignals(False)
        self.background_checkbox.setEnabled(
            bool(settings.enabled and self.service.background_supported)
        )
        if not self.service.background_supported:
            self.background_checkbox.setToolTip(
                "Closed-app reminders are available on Windows only."
            )

        parsed = QTime.fromString(settings.reminder_time, "HH:mm")
        self.time_edit.setTime(parsed if parsed.isValid() else QTime(20, 0))
        self.feedback.setVisible(False)

    def save(self) -> None:
        try:
            settings = self.service.save_settings(
                enabled=self.enabled_checkbox.isChecked(),
                reminder_time=self.time_edit.time().toString("HH:mm"),
                background_enabled=self.background_checkbox.isChecked(),
            )
        except NotificationError as error:
            self._show_feedback(str(error))
            return

        if settings.enabled and settings.background_enabled:
            self._show_feedback(
                f"Daily reminder enabled for {settings.reminder_time}, including when ChitLog is closed."
            )
        elif settings.enabled:
            self._show_feedback(
                f"Daily desktop reminder enabled for {settings.reminder_time}. "
                "It will run while ChitLog is open."
            )
        else:
            self._show_feedback("Daily desktop reminder disabled.")
        self.settings_changed.emit()
