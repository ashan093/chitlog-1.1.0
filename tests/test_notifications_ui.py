"""Offscreen Step 17 Settings/Notifications integration."""
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


def test_notifications_settings_page_is_connected():
    code = r"""
import secrets,tempfile
from pathlib import Path
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication
from chitlog.data.database import Database
from chitlog.data.notification_repository import NotificationRepository
from chitlog.services.notification_service import NotificationService
from chitlog.ui.main_window import create_window
from chitlog.ui.pages.notifications import NotificationsPage

app=QApplication([])
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    db=Database(root/'test.db',secrets.token_bytes(32),root/'snapshots').open()
    try:
        service=NotificationService(NotificationRepository(db))
        w=create_window(notification_service=service)
        page=w.page_widgets['Settings']
        assert isinstance(page, NotificationsPage)
        assert page.enabled_checkbox.isChecked() is False
        assert page.time_edit.time().toString('HH:mm')=='20:00'
        assert w.notification_controller is not None

        page.enabled_checkbox.setChecked(True)
        page.time_edit.setTime(QTime(18,45))
        page.save_button.click(); app.processEvents()
        saved=service.settings()
        assert saved.enabled is True
        assert saved.reminder_time=='18:45'
        assert 'enabled for 18:45' in page.feedback.text()

        w.navigate('Settings'); app.processEvents()
        assert w.current_page_name=='Settings'
        w.close()
    finally:
        db.close()
"""
    run_offscreen(code)
