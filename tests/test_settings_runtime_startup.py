"""Step 20 Settings page must construct successfully at real Qt runtime."""
import os
from pathlib import Path
import subprocess
import sys


def test_settings_page_constructs_offscreen_without_startup_attribute_errors():
    project = Path(__file__).resolve().parents[1]
    code = r"""
import secrets
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from chitlog.core.security import hash_secret, hash_security_answer
from chitlog.data.database import Database
from chitlog.data.settings_repository import SettingsRepository
from chitlog.services.settings_service import SettingsService
from chitlog.ui.pages.settings import SettingsPage

app = QApplication([])

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    db = Database(
        root / "settings.db",
        secrets.token_bytes(32),
        root / "snapshots",
    ).open()
    try:
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO auth_profile(id,login_method,secret_hash) "
                "VALUES (1,'password',?)",
                (hash_secret("password", "current-password"),),
            )
            connection.executemany(
                "INSERT INTO security_questions(position,question,answer_hash) "
                "VALUES (?,?,?)",
                [
                    (1, "Question one?", hash_security_answer("answer one")),
                    (2, "Question two?", hash_security_answer("answer two")),
                ],
            )
            connection.executemany(
                "INSERT INTO application_settings(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [
                    ("theme", "dark"),
                    ("currency_code", "LKR"),
                    ("currency_symbol", "Rs"),
                    ("setup_complete", "true"),
                ],
            )

        service = SettingsService(SettingsRepository(db))
        page = SettingsPage(
            service,
            notification_service=None,
            backup_service=None,
        )
        page.show()
        app.processEvents()

        assert page.current_secret_edit.maxLength() == 128
        assert page.new_secret_edit.maxLength() == 128
        assert page.confirm_secret_edit.maxLength() == 128
        assert page.recovery_current_secret.maxLength() == 128
        assert page.question_1.maxLength() == 120
        assert page.answer_1.maxLength() == 200

        page.close()
    finally:
        db.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
