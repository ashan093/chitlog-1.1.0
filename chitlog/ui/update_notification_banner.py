"""Verified-update notification banner for the ChitLog main window.

This widget never performs an update check or downloads software. It accepts
only an UpdateDecision that has already passed the secure updater pipeline.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
)

from chitlog.core.update_decision import (
    UpdateDecision,
    UpdateDisposition,
)
from chitlog.ui.theme import SPACE
from chitlog.ui.widgets import button, text_label


class UpdateNotificationBanner(QFrame):
    """One unobtrusive session-scoped notification for verified updates."""

    update_requested = Signal(object)
    dismissed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("updateNotificationBanner")
        self.setProperty("role", "glass")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self._decision: UpdateDecision | None = None
        self._dismissed_versions: set[str] = set()

        root = QHBoxLayout(self)
        root.setContentsMargins(
            SPACE["md"],
            SPACE["sm"],
            SPACE["md"],
            SPACE["sm"],
        )
        root.setSpacing(SPACE["md"])

        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(2)

        self.eyebrow_label = text_label("UPDATE AVAILABLE", "eyebrow")
        copy.addWidget(self.eyebrow_label)

        self.title_label = text_label("", "heading")
        self.title_label.setWordWrap(True)
        copy.addWidget(self.title_label)

        self.message_label = text_label("", "muted")
        self.message_label.setWordWrap(True)
        copy.addWidget(self.message_label)
        root.addLayout(copy, 1)

        actions = QVBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(SPACE["xs"])

        first_row = QHBoxLayout()
        first_row.setContentsMargins(0, 0, 0, 0)
        first_row.setSpacing(SPACE["xs"])

        self.update_now_button = button("Update Now", "primary")
        self.update_now_button.setEnabled(False)
        self.update_now_button.setToolTip(
            "Secure installer download will be connected in the next "
            "updater stage."
        )
        self.update_now_button.clicked.connect(self._request_update)
        first_row.addWidget(self.update_now_button)

        self.view_changes_button = button("View Changes")
        self.view_changes_button.clicked.connect(self._open_release_notes)
        first_row.addWidget(self.view_changes_button)

        actions.addLayout(first_row)

        self.later_button = button("Later")
        self.later_button.clicked.connect(self.dismiss_for_session)
        actions.addWidget(self.later_button)

        root.addLayout(actions)

        self.hide()

    @property
    def decision(self) -> UpdateDecision | None:
        return self._decision

    @property
    def current_version(self) -> str | None:
        decision = self._decision
        return None if decision is None else decision.available_version

    def present(self, decision: UpdateDecision) -> bool:
        """Present one verified decision.

        Returns True only when the banner is newly shown or changed. A version
        dismissed with Later stays hidden for the rest of this app session.
        """

        if not isinstance(decision, UpdateDecision):
            raise TypeError("decision must be an UpdateDecision.")

        if decision.disposition is UpdateDisposition.UP_TO_DATE:
            self.clear()
            return False

        version = decision.available_version
        if version in self._dismissed_versions:
            return False

        if (
            self._decision is not None
            and self._decision.available_version == version
            and self.isVisible()
        ):
            return False

        self._decision = decision

        if decision.disposition is UpdateDisposition.REQUIRED_UPDATE:
            self.eyebrow_label.setText("IMPORTANT UPDATE")
            self.title_label.setText(
                f"ChitLog {version} is marked as a required update"
            )
            self.message_label.setText(
                "This signed release is marked as required for supported "
                "use. Your local records remain available while you choose "
                "when to update."
            )
        else:
            self.eyebrow_label.setText("UPDATE AVAILABLE")
            self.title_label.setText(
                f"ChitLog {version} is available"
            )
            self.message_label.setText(
                "A newer signed version of ChitLog is available."
            )

        self.view_changes_button.setEnabled(
            self._release_notes_url(decision) is not None
        )
        self.show()
        self.raise_()
        return True

    def clear(self) -> None:
        self._decision = None
        self.hide()

    def dismiss_for_session(self) -> None:
        decision = self._decision
        if decision is None:
            self.hide()
            return

        version = decision.available_version
        self._dismissed_versions.add(version)
        self.hide()
        self.dismissed.emit(version)

    def enable_update_action(self, enabled: bool = True) -> None:
        """Reserved for the secure downloader stage."""

        self.update_now_button.setEnabled(bool(enabled))

    def _request_update(self) -> None:
        decision = self._decision
        if decision is not None:
            self.update_requested.emit(decision)

    @staticmethod
    def _release_notes_url(decision: UpdateDecision) -> QUrl | None:
        """Defense-in-depth validation before opening signed release notes."""

        raw = decision.payload.release_notes_url
        url = QUrl(raw)

        if (
            not url.isValid()
            or url.scheme().lower() != "https"
            or not url.host()
        ):
            return None

        return url

    def _open_release_notes(self) -> None:
        decision = self._decision
        if decision is None:
            return

        url = self._release_notes_url(decision)
        if url is None:
            self.view_changes_button.setEnabled(False)
            return

        # Explicit user click only. The URL came from the already verified
        # signed manifest and is checked again here for HTTPS + host.
        QDesktopServices.openUrl(url)
