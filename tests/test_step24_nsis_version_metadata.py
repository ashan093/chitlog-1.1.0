from pathlib import Path


def test_nsis_installer_has_file_version_metadata():
    project = Path(__file__).resolve().parents[1]
    script = (project / 'packaging' / 'installer' / 'ChitLog.nsi').read_text(encoding='utf-8')
    assert 'VIProductVersion "1.0.0.0"' in script
    assert 'VIAddVersionKey /LANG=1033 "ProductVersion" "1.0.0"' in script
    assert 'VIAddVersionKey /LANG=1033 "FileVersion" "1.0.0"' in script
