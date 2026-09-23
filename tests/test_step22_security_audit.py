"""Step 22 source-level security review."""
from pathlib import Path

from chitlog.core.security_audit import audit_project


def test_step22_static_security_audit_is_clean():
    project = Path(__file__).resolve().parents[1]
    issues = audit_project(project)
    assert issues == [], "\n".join(str(issue) for issue in issues)


def test_google_drive_oauth_v2_files_are_absent():
    project = Path(__file__).resolve().parents[1]
    assert not (project / "chitlog/core/google_drive_token_store.py").exists()
    assert not (project / "chitlog/services/google_drive_backup_service.py").exists()
    assert not (project / "chitlog/ui/pages/google_drive_backup.py").exists()
