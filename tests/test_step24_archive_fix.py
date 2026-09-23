from pathlib import Path


def test_build_uses_staging_copy_before_compressing():
    root = Path(__file__).resolve().parents[1]
    text = (root / "packaging" / "build_windows.ps1").read_text(encoding="utf-8")
    assert ".portable-staging" in text
    assert "robocopy $DistDir $StagingDir" in text
    assert 'Compress-Archive -Path (Join-Path $StagingDir "*")' in text
    assert "Stop-PackagedChitLogProcesses" in text


def test_existing_verified_dist_can_be_finalized_without_rebuild():
    root = Path(__file__).resolve().parents[1]
    script = root / "packaging" / "finalize_portable.ps1"
    text = script.read_text(encoding="utf-8")
    assert "verify_release.py" in text
    assert "LICENSES" in text
    assert "robocopy $DistDir $StagingDir" in text
    assert "CHITLOG STEP 24 PORTABLE FINALIZATION: PASS" in text
