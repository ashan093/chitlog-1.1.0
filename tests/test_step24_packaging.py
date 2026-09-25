from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_version_is_1_1_0():
    config = text("chitlog/core/config.py")
    assert 'from chitlog.core.version import APP_VERSION' in config


def test_proprietary_eula_preserves_open_source_rights_and_mentions_ads():
    eula = text("EULA.txt")
    assert "Ashan Madusanka" in eula
    assert "Copyright © 2026 Ashan Madusanka" in eula
    assert "personal use and for your own internal business use" in eula
    assert "Nothing in this Agreement restricts rights" in eula
    assert "GNU Lesser General Public License version 3" in eula
    assert "The Software may display advertising" in eula
    assert "private financial records" in eula


def test_qt_lgpl_notice_documents_dynamic_replacement_and_source_offer():
    notice = text("QT_LGPL_COMPLIANCE.txt")
    assert "one-folder mode" in notice
    assert "replace compatible LGPL-covered Qt shared libraries" in notice
    assert "at least three years" in notice
    assert "does not intentionally modify the Qt or PySide6" in notice


def test_pyinstaller_spec_is_onedir_windowed_and_carries_assets_and_icon():
    spec = text("packaging/ChitLog.spec")
    assert 'name="ChitLog"' in spec
    assert "console=False" in spec
    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert '"assets"' in spec
    assert '"keyring.backends.Windows"' in spec
    assert '"chit.ico"' in spec
    assert '"version_info.txt"' in spec


def test_build_script_gates_on_tests_security_licenses_and_release_verification():
    script = text("packaging/build_windows.ps1")
    assert "python -m pytest -q" in script
    assert "python -m chitlog.core.security_audit" in script
    assert "collect_licenses.py" in script
    assert "--preview-only --smoke-test" in script
    assert "verify_release.py" in script
    assert "ChitLog-1.1.0-windows-x64-portable.zip" in script


def test_installer_requires_eula_and_preserves_user_data():
    script = text("packaging/installer/ChitLog.nsi")
    assert "MUI_PAGE_LICENSE" in script
    assert "MUI_LICENSEPAGE_CHECKBOX" in script
    assert "MULTIUSER_EXECUTIONLEVEL Highest" in script
    assert "MULTIUSER_INSTALLMODE_DEFAULT_CURRENTUSER" in script
    assert "MULTIUSER_PAGE_INSTALLMODE" in script
    assert "$LOCALAPPDATA\\Programs\\ChitLog" in script
    assert "$PROGRAMFILES64\\ChitLog" in script
    assert '$LOCALAPPDATA\\Programs\\ChitLog' in script
    assert 'RMDir /r "$INSTDIR"' in script
    # User data must not be deleted from the AppLocalDataLocation tree.
    assert 'RMDir /r "$LOCALAPPDATA\\ChitLog"' not in script
    assert "preserved" in script.lower() or "not\n    ; removed" in script.lower()


def test_runtime_license_collector_requires_lgpl_payload():
    collector = text("packaging/collect_licenses.py")
    assert '"PySide6"' in collector
    assert '"sqlcipher3"' in collector
    assert '"argon2-cffi"' in collector
    assert '"keyring"' in collector
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in collector
    assert "GNU GENERAL PUBLIC LICENSE" in collector
    assert "https://www.gnu.org/licenses/lgpl-3.0.txt" in collector
    assert "https://www.gnu.org/licenses/gpl-3.0.txt" in collector
    assert "packaging/legal/" in collector
    assert "Do not distribute this build" in collector


def test_release_verifier_rejects_sensitive_data_types_and_developer_paths():
    verifier = text("packaging/verify_release.py")
    for suffix in (".db", ".chitlogbak", ".log", ".pfx"):
        assert suffix in verifier
    assert "Developer project path leaked" in verifier
    assert "SHA256SUMS.txt" in verifier
