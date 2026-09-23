"""Step 17 compact time-stepper regression test."""
import os
from pathlib import Path
import subprocess
import sys


def run_offscreen(code: str):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_reminder_time_uses_small_themed_toolbuttons():
    code = r"""
import secrets,tempfile
from pathlib import Path
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication,QToolButton
from chitlog.data.database import Database
from chitlog.data.notification_repository import NotificationRepository
from chitlog.services.notification_service import NotificationService
from chitlog.ui.pages.notifications import NotificationsPage

app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        page=NotificationsPage(NotificationService(NotificationRepository(db)))
        page.show(); app.processEvents()

        assert isinstance(page.time_up_button,QToolButton)
        assert isinstance(page.time_down_button,QToolButton)
        assert page.time_up_button.property('timeStepper') is True
        assert page.time_down_button.property('timeStepper') is True
        assert (page.time_up_button.width(),page.time_up_button.height())==(20,14)
        assert (page.time_down_button.width(),page.time_down_button.height())==(20,14)
        assert page.time_up_button.text()=='▴'
        assert page.time_down_button.text()=='▾'

        page.time_edit.setTime(QTime(20,14))
        page.time_up_button.click(); app.processEvents()
        assert page.time_edit.time().toString('HH:mm')=='20:15'
        page.time_down_button.click(); app.processEvents()
        assert page.time_edit.time().toString('HH:mm')=='20:14'
        page.close()
    finally:
        db.close()
"""
    run_offscreen(code)
