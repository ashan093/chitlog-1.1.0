"""Bounded, best-effort cleanup for ChitLog's updater-owned cache.

Only direct child files with ChitLog updater-controlled names are eligible.
The cleaner never recurses, never follows symbolic links, and never touches
unknown files.  Active/current artifacts supplied by the caller are protected
unconditionally.

Cleanup is deliberately non-critical.  The public best-effort wrapper absorbs
all cleanup failures so disk housekeeping can never block a verified update or
normal ChitLog operation.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import time
from typing import Iterable


UPDATE_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
UPDATE_CACHE_MIN_DELETE_AGE_SECONDS = 24 * 60 * 60
UPDATE_CACHE_MAX_RETAINED_FILES = 12

_VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
_FINAL_PATTERNS = (
    re.compile(rf"^ChitLog-{_VERSION}-Setup\.exe$"),
    re.compile(rf"^ChitLog-{_VERSION}-handoff\.json$"),
    re.compile(rf"^ChitLogUpdater-{_VERSION}\.exe$"),
)
_PART_PATTERN = re.compile(
    rf"^\.(?:ChitLog-{_VERSION}-(?:Setup|handoff)|"
    rf"ChitLogUpdater-{_VERSION})-[A-Za-z0-9_.-]+\.part$"
)


@dataclass(frozen=True, slots=True)
class UpdateCacheCleanupReport:
    scanned_files: int = 0
    eligible_files: int = 0
    deleted_files: int = 0
    protected_files: int = 0
    recent_files: int = 0
    skipped_unknown: int = 0
    skipped_unsafe: int = 0
    failed_deletions: int = 0
    aborted: bool = False


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: Path
    mtime: float
    protected: bool


def _is_managed_update_name(name: str) -> bool:
    return any(pattern.fullmatch(name) for pattern in _FINAL_PATTERNS) or bool(
        _PART_PATTERN.fullmatch(name)
    )


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _validate_cleanup_limits(
    *,
    max_age_seconds: int,
    min_delete_age_seconds: int,
    max_retained_files: int,
) -> None:
    for value, label in (
        (max_age_seconds, "max_age_seconds"),
        (min_delete_age_seconds, "min_delete_age_seconds"),
        (max_retained_files, "max_retained_files"),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{label} must be an integer.")
        if value < 0:
            raise ValueError(f"{label} must not be negative.")

    if max_age_seconds < min_delete_age_seconds:
        raise ValueError(
            "max_age_seconds must be greater than or equal to "
            "min_delete_age_seconds."
        )


def cleanup_update_cache(
    cache_directory: str | Path,
    *,
    protected_paths: Iterable[str | Path] = (),
    max_age_seconds: int = UPDATE_CACHE_MAX_AGE_SECONDS,
    min_delete_age_seconds: int = UPDATE_CACHE_MIN_DELETE_AGE_SECONDS,
    max_retained_files: int = UPDATE_CACHE_MAX_RETAINED_FILES,
    now: float | None = None,
) -> UpdateCacheCleanupReport:
    """Delete only stale, updater-owned direct children of one cache directory.

    Files older than ``max_age_seconds`` are removed.  A second count bound
    removes the oldest remaining files only after they have reached
    ``min_delete_age_seconds``.  Therefore fresh artifacts are never sacrificed
    merely to satisfy the count bound.
    """

    _validate_cleanup_limits(
        max_age_seconds=max_age_seconds,
        min_delete_age_seconds=min_delete_age_seconds,
        max_retained_files=max_retained_files,
    )

    root = Path(cache_directory)
    if not root.exists():
        return UpdateCacheCleanupReport()

    try:
        if root.is_symlink():
            return UpdateCacheCleanupReport(skipped_unsafe=1, aborted=True)
        resolved_root = root.resolve(strict=True)
    except OSError:
        return UpdateCacheCleanupReport(skipped_unsafe=1, aborted=True)

    if not resolved_root.is_dir():
        return UpdateCacheCleanupReport(skipped_unsafe=1, aborted=True)

    protected = {_normalized_path(path) for path in protected_paths}
    timestamp = time.time() if now is None else float(now)

    scanned = 0
    unknown = 0
    unsafe = 0
    failures = 0
    candidates: list[_Candidate] = []

    try:
        entries = list(os.scandir(resolved_root))
    except OSError:
        return UpdateCacheCleanupReport(skipped_unsafe=1, aborted=True)

    for entry in entries:
        scanned += 1
        if not _is_managed_update_name(entry.name):
            unknown += 1
            continue

        try:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                unsafe += 1
                continue
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            unsafe += 1
            continue

        path = resolved_root / entry.name
        candidates.append(
            _Candidate(
                path=path,
                mtime=float(stat.st_mtime),
                protected=_normalized_path(path) in protected,
            )
        )

    deleted = 0
    protected_count = sum(1 for item in candidates if item.protected)
    deleted_paths: set[str] = set()

    def delete_candidate(item: _Candidate) -> bool:
        nonlocal deleted, failures
        try:
            item.path.unlink()
        except OSError:
            failures += 1
            return False
        deleted += 1
        deleted_paths.add(_normalized_path(item.path))
        return True

    # Age retention is the primary bound.
    for item in sorted(candidates, key=lambda value: (value.mtime, value.path.name)):
        if item.protected:
            continue
        age = max(0.0, timestamp - item.mtime)
        if age >= max_age_seconds:
            delete_candidate(item)

    survivors = [
        item
        for item in candidates
        if _normalized_path(item.path) not in deleted_paths
    ]

    # Count retention is secondary. Only artifacts old enough to be safely
    # stale are candidates, so a burst of fresh updater files is left intact.
    excess = max(0, len(survivors) - max_retained_files)
    if excess:
        count_candidates = [
            item
            for item in survivors
            if not item.protected
            and max(0.0, timestamp - item.mtime) >= min_delete_age_seconds
        ]
        count_candidates.sort(key=lambda value: (value.mtime, value.path.name))
        for item in count_candidates[:excess]:
            delete_candidate(item)

    recent = 0
    for item in candidates:
        if item.protected or _normalized_path(item.path) in deleted_paths:
            continue
        if max(0.0, timestamp - item.mtime) < min_delete_age_seconds:
            recent += 1

    return UpdateCacheCleanupReport(
        scanned_files=scanned,
        eligible_files=len(candidates),
        deleted_files=deleted,
        protected_files=protected_count,
        recent_files=recent,
        skipped_unknown=unknown,
        skipped_unsafe=unsafe,
        failed_deletions=failures,
        aborted=False,
    )


def cleanup_update_cache_best_effort(
    cache_directory: str | Path,
    *,
    protected_paths: Iterable[str | Path] = (),
) -> UpdateCacheCleanupReport:
    """Run updater cache cleanup without ever making cleanup a blocker."""

    try:
        return cleanup_update_cache(
            cache_directory,
            protected_paths=protected_paths,
        )
    except Exception:
        # Cache housekeeping is intentionally below updater integrity and
        # availability. Validation/execution paths must continue even if local
        # cleanup encounters an unexpected platform/filesystem condition.
        return UpdateCacheCleanupReport(failed_deletions=1, aborted=True)
