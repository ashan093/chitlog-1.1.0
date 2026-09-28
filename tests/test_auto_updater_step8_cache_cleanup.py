"""Step 8D tests for bounded, best-effort updater cache cleanup."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from chitlog.core import update_cache_cleanup as cleanup


NOW = 2_000_000_000.0
DAY = 24 * 60 * 60


def _write(path: Path, *, age_seconds: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = NOW - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def test_cleanup_deletes_only_old_managed_direct_children(tmp_path):
    root = tmp_path / "cache" / "updates"
    stale = _write(root / "ChitLog-1.2.0-Setup.exe", age_seconds=8 * DAY)
    nested = _write(
        root / "nested" / "ChitLog-1.1.0-Setup.exe",
        age_seconds=40 * DAY,
    )
    unknown = _write(root / "keep-me.txt", age_seconds=40 * DAY)

    report = cleanup.cleanup_update_cache(root, now=NOW)

    assert not stale.exists()
    assert nested.is_file()
    assert unknown.is_file()
    assert report.deleted_files == 1
    assert report.skipped_unknown >= 1


def test_cleanup_recognizes_installer_handoff_updater_and_part_files(tmp_path):
    root = tmp_path / "updates"
    names = (
        "ChitLog-1.2.0-Setup.exe",
        "ChitLog-1.2.0-handoff.json",
        "ChitLogUpdater-1.2.0.exe",
        ".ChitLog-1.2.0-Setup-abc123.part",
        ".ChitLog-1.2.0-handoff-abc123.part",
        ".ChitLogUpdater-1.2.0-abc123.part",
    )
    paths = [_write(root / name, age_seconds=8 * DAY) for name in names]

    report = cleanup.cleanup_update_cache(root, now=NOW)

    assert all(not path.exists() for path in paths)
    assert report.eligible_files == len(paths)
    assert report.deleted_files == len(paths)


def test_protected_current_installer_is_never_deleted(tmp_path):
    root = tmp_path / "updates"
    active = _write(root / "ChitLog-1.2.0-Setup.exe", age_seconds=90 * DAY)
    stale = _write(root / "ChitLogUpdater-1.1.0.exe", age_seconds=90 * DAY)

    report = cleanup.cleanup_update_cache(
        root,
        protected_paths=(active,),
        now=NOW,
        max_retained_files=0,
    )

    assert active.is_file()
    assert not stale.exists()
    assert report.protected_files == 1


def test_fresh_files_are_not_deleted_just_to_satisfy_count_bound(tmp_path):
    root = tmp_path / "updates"
    paths = [
        _write(root / f"ChitLogUpdater-1.0.{index}.exe", age_seconds=60)
        for index in range(8)
    ]

    report = cleanup.cleanup_update_cache(
        root,
        now=NOW,
        max_retained_files=2,
    )

    assert all(path.is_file() for path in paths)
    assert report.deleted_files == 0
    assert report.recent_files == len(paths)


def test_count_bound_deletes_oldest_safe_candidates(tmp_path):
    root = tmp_path / "updates"
    paths = []
    for index in range(6):
        paths.append(
            _write(
                root / f"ChitLogUpdater-1.0.{index}.exe",
                age_seconds=(2 * DAY) + (index * 60),
            )
        )

    report = cleanup.cleanup_update_cache(
        root,
        now=NOW,
        max_age_seconds=30 * DAY,
        min_delete_age_seconds=DAY,
        max_retained_files=3,
    )

    assert report.deleted_files == 3
    assert sum(path.exists() for path in paths) == 3


def test_symlink_cache_or_symlink_artifact_is_never_followed(tmp_path):
    real_root = tmp_path / "real-updates"
    real_root.mkdir()
    outside = _write(tmp_path / "outside.exe", age_seconds=40 * DAY)

    link_root = tmp_path / "updates-link"
    try:
        link_root.symlink_to(real_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are unavailable in this environment.")

    report = cleanup.cleanup_update_cache(link_root, now=NOW)
    assert report.aborted is True
    assert outside.is_file()

    artifact_link = real_root / "ChitLog-1.2.0-Setup.exe"
    try:
        artifact_link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("File symbolic links are unavailable in this environment.")

    report = cleanup.cleanup_update_cache(real_root, now=NOW)
    assert artifact_link.is_symlink()
    assert outside.is_file()
    assert report.skipped_unsafe >= 1


def test_best_effort_wrapper_absorbs_unexpected_cleanup_failure(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(cleanup, "cleanup_update_cache", fail)

    report = cleanup.cleanup_update_cache_best_effort(tmp_path / "updates")

    assert report.aborted is True
    assert report.failed_deletions == 1


def test_launcher_integrates_best_effort_cleanup_before_staging():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_updater_launch.py"
    ).read_text(encoding="utf-8")

    cleanup_call = "cleanup_update_cache_best_effort("
    stage_call = "staged_updater = stage_packaged_updater("

    assert cleanup_call in source
    assert "protected_paths=(installer.path,)" in source
    assert source.index(cleanup_call) < source.index(stage_call)


def test_cleanup_module_has_no_recursion_process_or_financial_access():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_cache_cleanup.py"
    ).read_text(encoding="utf-8")

    assert "os.scandir(resolved_root)" in source
    assert "entry.is_symlink()" in source
    assert "follow_symlinks=False" in source

    for forbidden in (
        "rglob(",
        "os.walk(",
        "subprocess",
        "Popen",
        "ShellExecute",
        "TerminateProcess",
        "Database(",
        "TransactionRepository",
        "WorkerRepository",
        "LiabilityRepository",
        "BudgetRepository",
    ):
        assert forbidden not in source
