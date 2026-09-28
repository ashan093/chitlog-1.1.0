# ChitLog Auto-Updater Build Guide

Last updated: 2026-09-28
Current branch: `feature/auto-updater`
Current implementation checkpoint: `13c8349` — `Harden updater cache cleanup`
Target application version: `1.1.0`

## Purpose

This document records the ChitLog automatic-updater implementation as a reproducible engineering guide. It is updated after each successful Git checkpoint so the full design, security assumptions, implementation sequence, verification evidence, and release procedure remain available after development is complete.

## Development Discipline

- Work one updater checkpoint at a time.
- Keep the working tree clean before applying a new checkpoint patch.
- Pin each patch to the expected branch and HEAD when practical.
- Run dedicated tests for the current checkpoint.
- Run relevant focused regression tests.
- Run the full test suite.
- Run `python -m chitlog.core.security_audit`.
- Run `git diff --check`.
- Inspect `git status --short`.
- Commit and push only after the outputs have been reviewed.
- Do not claim a Windows packaging or VM test passed until it was actually run on Windows.
- Preserve user financial data as the highest-priority invariant.

## Updater Architecture

The implemented update path is designed around a signed release manifest rather than blindly trusting a downloaded executable.

1. ChitLog fetches the configured HTTPS update manifest.
2. The manifest is strictly parsed and verified with Ed25519.
3. Version/update policy decides whether the release is applicable.
4. The installer is downloaded through the restricted updater transport.
5. Installer size and SHA-256 are verified against the signed manifest.
6. ChitLog creates a signed/verified updater handoff.
7. A separately packaged `ChitLogUpdater.exe` is staged and launched.
8. ChitLog exits only after the updater process starts successfully.
9. The standalone updater re-verifies the handoff and installer.
10. It waits for the originating ChitLog process without forcibly terminating it.
11. The verified NSIS installer is started with elevation.
12. After successful installation, the updater relaunches the exact installed ChitLog executable.

Current authenticity root: Ed25519-signed manifest plus exact installer SHA-256. Authenticode is not currently mandatory because the existing NSIS installer workflow is not code-signed.

---

## Completed Checkpoints

### Step 1 — Version and Update Foundation

Established centralized application version/update policy and the initial updater architecture.

Key outcome:
- Version/update state moved into dedicated core modules.
- Future updater logic can make deterministic version and channel decisions without scattering version strings through the application.

### Step 2 — Signed Manifest and Ed25519 Verification

Implemented strict signed update manifest handling and Ed25519 public-key verification.

Key outcomes:
- Canonical manifest payload bytes are signed.
- Manifest parsing is strict.
- Public verification keys are separated from future private release-signing material.
- Frozen cryptographic verification was later tested as part of packaging.

### Step 3 — Update Decision, Restricted Transport, and Check Pipeline

Implemented the secure update-check pipeline.

Key outcomes:
- HTTPS-only restricted transport.
- Strict manifest parsing and signature verification before update decisions.
- Update applicability decisions separated from transport and UI concerns.
- Core accounting functionality remains independent from network/update-check failures.

### Step 4 — Update Preferences and Background Checks

Added update preferences and non-blocking manual/automatic update checks.

Important implementation decision:
- Dedicated `QThread` subclasses are used for updater background work.
- Do not reintroduce the earlier `QObject.moveToThread` design; the dedicated-thread implementation fixed a real Windows stability problem.

### Step 5 — Verified Update Notification / Privacy Wording

Added update-availability UI while keeping private financial data out of updater network activity.

Key outcomes:
- Update notifications represent only verified update state.
- Update checks do not transmit transaction, worker, payroll, budget, liability, or other private accounting records.

### Step 6 — Secure Installer Download and Staging

Added verified installer download/staging.

Key outcomes:
- Installer is downloaded to a temporary same-directory staging file.
- Exact expected size and SHA-256 are checked.
- Final staging uses an atomic replacement.
- Downloaded installers are not executed by the download worker.
- The installer is verified again later before execution.

### Step 7A — Signed Updater Handoff

Implemented the offline handoff between ChitLog and the standalone updater.

Key outcomes:
- Handoff includes the signed manifest and required metadata.
- Handoff loading independently re-verifies release/signature/policy/path details.
- Handoff writes are atomic.
- This layer does not perform network access or execute the installer.

### Step 7B — Standalone Updater Process Foundation

Added `python -m chitlog.updater --handoff <absolute-path>` and safe parent-process waiting.

Key outcomes:
- Windows process wait uses native synchronization rather than forced termination.
- Handoff is verified before and after the originating ChitLog process exits.

### Step 7C — Verified Installer Execution

Added the first installer execution path.

Key outcomes:
- Installer size/hash are verified immediately before execution.
- NSIS installer is elevated with Windows `runas`.
- UAC cancellation, installer failure, and successful completion remain distinguishable.
- No raw user-controlled installer command line is constructed.

Important compatibility decision:
- The NSIS bootstrap may be PE i386 or AMD64.
- Signed manifest architecture `x64` describes the ChitLog release, not necessarily the NSIS bootstrap executable machine type.

### Step 7D — Main App to Standalone Updater Launch

Connected the verified update flow to `ChitLogUpdater.exe`.

Key outcomes:
- Packaged updater is staged and verified before launch.
- ChitLog exits only after updater startup succeeds.
- If updater launch fails, ChitLog remains running.

### Step 7E — Post-Install Relaunch

Implemented controlled ChitLog relaunch after a successful update.

Key outcomes:
- Handoff binds to the exact originating ChitLog executable.
- After installer exit code `0`, the expected installed `ChitLog.exe` is validated and relaunched.
- Relaunch failure is reported without falsely claiming the installation failed.

### Step 7F — Frozen `ChitLogUpdater.exe`

Commit: `6765daf` — `build: package standalone ChitLog updater`

Added:
- `packaging/ChitLogUpdater.spec`
- `packaging/updater_entry.py`
- `packaging/verify_frozen_updater.py`
- `packaging/build_updater.ps1`
- updater packaging tests

Key outcomes:
- Standalone one-file windowless updater.
- PySide6 excluded from updater package.
- Frozen self-test verifies critical updater imports and Ed25519 public verification.
- Frozen updater verifier checks PE/x64 shape and calculates SHA-256.
- Verified updater is copied beside `ChitLog.exe`.

### Step 8A — NSIS Safe In-Place Upgrade Foundation

Commit: `2ee381f` — `build: prepare NSIS for safe in-place upgrades`

Key outcomes:
- NSIS remembers/restores existing installation scope.
- Existing custom installation directory is restored for upgrades.
- Fresh current-user installs continue to default to LocalAppData.
- All-users installations use Program Files with elevation.
- Program files are overwritten in place rather than deleting the installation tree first.
- Per-user ChitLog finance data remains outside `$INSTDIR`.
- Installer build refuses to proceed without a verified `ChitLogUpdater.exe`.
- Updater SHA-256/size are checked before and across installer compilation.
- NSIS successful completion is explicitly exit code `0`.

### Step 8B — Pre-Migration Recovery Snapshot Hardening

Commit: `87a18c4` — `Harden pre-migration recovery snapshots`

Purpose:
Protect an existing encrypted ChitLog database before a newer application version performs schema migration.

Key outcomes:
- Live database is validated before the migration snapshot is accepted.
- Snapshot captures source `application_id` and `user_version`.
- Recovery copy is created before migration.
- The snapshot connection is closed and reopened as a fresh connection.
- Reopened snapshot is fully validated.
- Snapshot metadata must match the source database.
- Invalid/incomplete recovery snapshots are deleted rather than retained.
- Recovery rotation occurs only after the persisted snapshot has been proven reopenable.
- A failed pre-migration recovery snapshot prevents migration from advancing.

Validation recorded before commit:
- dedicated recovery tests passed
- focused database/update tests passed
- full suite passed
- security audit passed
- `git diff --check` passed

### Step 8C — Packaging Pipeline Integration

Commit: `0808292` — `build: integrate updater into Windows release pipeline`

Files:
- `packaging/build_windows.ps1`
- `tests/test_auto_updater_step8_packaging_pipeline.py`

Purpose:
Remove the manual ordering dependency between the normal ChitLog Windows build and the standalone updater build.

New normal release flow:

`build_windows.ps1`
→ build `ChitLog.exe`
→ collect runtime licenses
→ automatically run existing `build_updater.ps1`
→ build and frozen-verify `ChitLogUpdater.exe`
→ copy updater beside `ChitLog.exe`
→ one-folder release verification
→ create portable release archive

Then:

`build_installer.ps1`
→ independently verify packaged updater again
→ compile NSIS installer
→ verify updater hash/size remained stable
→ produce installer SHA-256

Windows verification results:
- Step 8C dedicated tests: `6 passed`
- focused packaging/updater regression group: `29 passed`
- full suite inside Windows build: `708 passed, 1 skipped`
- standalone updater build tests: `75 passed`
- frozen updater verification: PASS
- packaged updater size: `13,871,867 bytes`
- packaged updater SHA-256: `1a7a8a87f3c0d85b9f721b07c2c21b370c8415e46d432352e1fe74ff1a5398bc`
- one-folder release verification: PASS
- portable release creation: PASS
- NSIS Step 8A upgrade build: PASS
- installer SHA-256: `eb5a6c578e659763238a5ef39e9943f2f9d1a2e628d30af0da6302aa3ea9266b`
- final full suite: `708 passed, 1 skipped`
- security audit: PASS
- `git diff --check`: clean
- commit pushed to `origin/feature/auto-updater`

This checkpoint means a normal Windows release build can no longer accidentally omit the standalone updater simply because the developer forgot to run `build_updater.ps1` manually.

---

## Current Checkpoint

Branch: `feature/auto-updater`
Implementation commit: `13c8349`
Remote: `origin/feature/auto-updater`
Working tree after checkpoint: clean

## Completed Step 8D Checkpoint

### Step 8D — Bounded Updater Cache Cleanup

Base commit: `0808292`
Checkpoint commit message: `Harden updater cache cleanup`
Implementation commit: `13c8349` — pushed to `origin/feature/auto-updater`.

Purpose:
- prevent updater-owned cache artifacts from accumulating indefinitely;
- clean stale staged installers, handoffs, staged updater copies, and interrupted `.part` files;
- never recurse outside the updater-owned `cache\updates` directory supplied by ChitLog;
- never follow symbolic links;
- never touch unknown filenames;
- unconditionally protect the installer currently selected for launch;
- preserve fresh artifacts even when the count limit is temporarily exceeded;
- make cleanup best-effort so cleanup failure can never block an otherwise verified update.

Implementation design:
- new `chitlog/core/update_cache_cleanup.py` owns the retention policy;
- only strict ChitLog updater filename patterns are eligible;
- primary retention bound: remove managed files at least 7 days old;
- secondary count bound: retain at most 12 managed files when excess files are at least 24 hours old;
- fresh files under 24 hours are not deleted merely to meet the count target;
- cleanup scans direct children with `os.scandir` and does not recurse;
- symlink cache roots and symlink artifacts are skipped/refused;
- `cleanup_update_cache_best_effort()` absorbs unexpected cleanup failures;
- `prepare_and_launch_updater()` calls cleanup before staging the new updater/handoff and passes the verified installer as a protected path;
- database files, backups, application settings, reports, and financial/user records are outside the cleaner's managed filename set and cleanup scope.

Windows verification performed on the real `feature/auto-updater` working tree:
- dedicated Step 8D tests: `8 passed, 1 skipped in 0.33s`;
- the skipped dedicated test is the explicit Windows/environment symlink-availability guard;
- focused Step 6/7/8D updater regressions: `97 passed, 1 skipped in 1.96s`;
- complete application suite: `716 passed, 2 skipped in 49.32s`;
- `python -m chitlog.core.security_audit`: `CHITLOG SECURITY REVIEW: PASS`;
- security audit found no forbidden script execution, broad network client, embedded web engine, hard-coded credential literal, developer path, SQL trace, or deferred Google Drive module;
- `git diff --check`: clean;
- reviewed working-tree scope before commit:
  - modified `chitlog/core/update_updater_launch.py`;
  - new `chitlog/core/update_cache_cleanup.py`;
  - new `tests/test_auto_updater_step8_cache_cleanup.py`;
  - new `docs/ChitLog_AutoUpdater_Build_Guide.md`.

Acceptance conclusion:
Step 8D meets the bounded-cleanup requirement without weakening the signed-manifest, installer-hash, handoff, or standalone-updater trust boundaries. Cleanup is limited to updater-owned direct children, protects the currently selected installer, avoids recursive/symlink traversal, and is deliberately non-fatal.

---

## Remaining Production Work

### Step 9 — Production Trust Bootstrap
- Create the production Ed25519 release-signing key outside the source repository.
- Embed only the public key/key identifier.
- Define secure storage, rotation, and revocation procedures.
- Test a production-format signed manifest.

### Step 10 — Cloudflare Update Endpoint
- Implement the final Windows stable-update endpoint.
- Serve only signed update metadata required by ChitLog.
- Keep financial/private user data completely outside the update service.

### Step 11 — Release / Signing Tooling
- Deterministically hash the final installer.
- Construct strict manifest payload.
- Sign using the offline/private release key.
- Produce/publish installer, release notes, hashes, and manifest safely.

### Step 12 — Real 1.0.0 → 1.1.0 VM Upgrade Test
On a clean disposable Windows VM:
- install real ChitLog 1.0.0
- create realistic disposable finance/worker/settings data
- perform the real update to 1.1.0
- verify database/settings survive
- verify recovery snapshot
- verify updater handoff/elevation/relaunch
- verify shortcuts/uninstaller/install path
- verify no developer paths are exposed

### Step 13 — Release Finalization
- resolve remaining blockers
- final full test/security/package audit
- merge updater branch
- tag release
- publish installer and signed manifest
- verify live update check from the released build
