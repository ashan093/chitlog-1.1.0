from pathlib import Path


def test_installer_builder_does_not_index_scalar_candidate_path():
    project = Path(__file__).resolve().parents[1]
    script = (project / "packaging" / "build_installer.ps1").read_text(encoding="utf-8")
    assert "$Candidates[0]" not in script
    assert "foreach ($CandidatePath in $CandidatePaths)" in script
    assert "Test-Path -LiteralPath $CandidatePath" in script
    assert "NSIS compiler: $MakeNsisPath" in script
