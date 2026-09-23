"""Tests use temporary folders, never real ChitLog data."""
from pathlib import Path
import pytest
from chitlog.core.config import AppPaths
from chitlog.core.logging_config import configure_logging, close_logging


def test_directories_preserve_existing_data(tmp_path):
    paths = AppPaths(tmp_path / "ChitLog")
    paths.ensure()
    marker = paths.data / "existing.txt"
    marker.write_text("keep me", encoding="utf-8")
    paths.ensure()
    assert marker.read_text(encoding="utf-8") == "keep me"
    assert all(p.is_dir() for p in (paths.logs, paths.data, paths.cache, paths.backups))
    assert list(paths.cache.iterdir()) == []


def test_conflicting_file_is_not_overwritten(tmp_path):
    root = tmp_path / "ChitLog"
    root.mkdir()
    (root / "logs").write_text("preserve", encoding="utf-8")
    with pytest.raises(OSError):
        AppPaths(root).ensure()
    assert (root / "logs").read_text(encoding="utf-8") == "preserve"


def test_relative_data_path_rejected():
    with pytest.raises(ValueError):
        AppPaths(Path("relative")).ensure()


def test_permission_failure_propagates(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(PermissionError):
        AppPaths(tmp_path / "ChitLog").ensure()


def test_logging_reinitialization_and_secret_rejection(tmp_path):
    logger = configure_logging(tmp_path)
    logger = configure_logging(tmp_path)
    try:
        logger.info("application_started")
        logger.info("secret_password_123")
        logger.info("application_started", "secret_password_123")
        try:
            raise ValueError("secret_password_123")
        except ValueError:
            logger.exception("startup_failed")
    finally:
        close_logging(logger)
    text = (tmp_path / "chitlog.log").read_text(encoding="utf-8")
    assert text.count("application_started") == 1
    assert "secret_password_123" not in text
    assert "Traceback" not in text


def test_log_rotation_is_bounded(tmp_path):
    logger = configure_logging(tmp_path)
    handler = logger.handlers[0]
    assert handler.maxBytes == 1_048_576
    assert handler.backupCount == 3
    handler.maxBytes = 128
    try:
        for _ in range(50):
            logger.info("application_started")
    finally:
        close_logging(logger)
    files = list(tmp_path.glob("chitlog.log*"))
    assert len(files) == 4
    assert all(p.stat().st_size <= 128 for p in files)


def test_launch_from_another_directory(tmp_path):
    import os
    import subprocess
    import sys
    project = Path(__file__).resolve().parents[1]
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    # A subprocess checks real application startup with Qt's isolated test paths.
    code = (
        "import sys; from PySide6.QtCore import QStandardPaths; "
        "QStandardPaths.setTestModeEnabled(True); "
        "sys.path.insert(0, sys.argv.pop(1)); "
        "from chitlog.application import main; raise SystemExit(main())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(project), "--smoke-test", "--preview-only"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "data").exists()


def test_logo_fallback(tmp_path):
    import os
    import subprocess
    import sys
    project = Path(__file__).resolve().parents[1]
    code = '''
from pathlib import Path
from PySide6.QtWidgets import QApplication, QLabel
from chitlog.ui.main_window import create_window
app = QApplication([])
w = create_window(Path("missing-assets"))
w.show()
app.processEvents()
assert any(label.text() == "ChitLog" for label in w.findChildren(QLabel))
w.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
