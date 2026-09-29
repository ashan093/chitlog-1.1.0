# ChitLog Auto-Updater Build Guide

Last updated: 2026-09-29
Current branch: `feature/auto-updater`
Current implementation checkpoint: `cae99be` — `fix: make release signer runnable by file path`
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
Implementation commit: `cae99be`
Implementation message: `fix: make release signer runnable by file path`
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

## Completed Step 9 Checkpoint

### Step 9 — Production Trust Bootstrap

Base repository HEAD: `859c6fd`
Implementation commit: `0c986a1` — `security: establish production update trust`
Remote status: pushed to `origin/feature/auto-updater`
Checkpoint status: implementation committed and pushed.

Production trust anchor:
- algorithm: Ed25519;
- key ID: `chitlog-update-2026-01`;
- raw public key: `d6a28064cc1352c6fcb64fdc2c9e275ca0e4ff15dfc0a33757d69057633501d2`;
- public-key SHA-256 fingerprint: `eeb2edd191b0074c318db350001491fd89e94801a087685a4223052ec2d0151b`;
- only the public key is embedded in the application.

Private-key handling:
- the production private key was generated outside the Git repository;
- it is stored as an encrypted PKCS#8 Ed25519 PEM;
- its passphrase is separate from the key file and must never be committed, logged, pasted into ChatGPT, or bundled with ChitLog;
- keep at least one secure offline backup of the encrypted private key;
- do not place the signing-key directory inside the repository or a cloud-synchronized development folder.

Production proof:
- the locally held private key derived the exact embedded public key;
- the public-key SHA-256 fingerprint matched the recorded fingerprint;
- the real private key signed ChitLog's canonical strict manifest payload;
- proof canonical payload SHA-256: `9be6a2ea90f8970120117b34a985907f39615fc057434ce3477cb4f749db5a16`;
- the resulting Ed25519 signature verified against the production public key;
- only the public proof manifest/signature are committed for regression testing.

Rotation procedure:
1. Generate a new encrypted Ed25519 key outside the repository.
2. Add the new public key under a new key ID while retaining the old trusted public key.
3. Ship a ChitLog release that trusts both IDs.
4. Begin signing new manifests with the new private key only after that dual-trust release is sufficiently deployed.
5. In a later trusted ChitLog release, remove the retired old public-key ID.

Revocation procedure:
1. Stop signing immediately with a suspected compromised private key.
2. Remove its key ID from `TRUSTED_UPDATE_PUBLIC_KEYS` in the next safely distributed ChitLog build.
3. Add a replacement public key under a new key ID.
4. Publish manifests only under an uncompromised trusted key.
5. Do not reuse a revoked key ID.

Important limitation:
A client that has not yet received a release containing the replacement trust anchor cannot learn to trust a new key solely from a manifest signed by a compromised or unknown key. Emergency recovery therefore requires a separately trusted software distribution path.

Windows verification completed before commit:
- dedicated Step 9 production-trust tests: `7 passed in 0.09s`;
- existing Step 2 signature tests: `20 passed in 0.12s`;
- initial focused updater/trust group: `74 passed, 1 skipped in 0.94s`;
- legacy Step 2 packaging regression was reviewed after it correctly exposed an obsolete pre-Step-9 assumption that the production registry must be empty;
- that regression was narrowed to the real security invariant: the frozen packaging self-test key ID must not appear in the production trust registry;
- corrected Step 2 packaging regression: `6 passed in 0.08s`;
- combined Step 2 signature + Step 2 packaging + Step 9 production-trust group: `33 passed in 0.18s`;
- complete application suite after correction: `724 passed, 2 skipped in 44.29s`;
- `python -m chitlog.core.security_audit`: `CHITLOG SECURITY REVIEW: PASS`;
- `git diff --check`: no errors; Windows emitted only normal LF-to-CRLF conversion notices;
- reviewed Step 9 working-tree scope:
  - modified `chitlog/core/update_signature.py`;
  - modified `tests/test_auto_updater_step2_signature.py`;
  - modified `tests/test_auto_updater_step2_packaging.py`;
  - added `tests/test_auto_updater_step9_production_trust.py`;
  - modified `docs/ChitLog_AutoUpdater_Build_Guide.md`.

Acceptance conclusion:
Step 9 establishes the first real ChitLog production Ed25519 trust anchor while keeping all private signing material outside the repository and application. The real production private key has been locally proven to match the embedded public key and to sign the exact canonical manifest format verified by ChitLog. Rotation and revocation procedures are documented, and the packaging-only test key remains explicitly excluded from production trust.

---

## Completed Step 10 Checkpoint

### Step 10 — Cloudflare Update Endpoint

#### Step 10A — Dedicated fail-closed Cloudflare Worker

Live Worker:
- Worker name: `chitlog-updates`;
- live origin: `https://chitlog-updates.chitlogapp.workers.dev`;
- verified health endpoint: `/healthz` returns HTTP `200` with JSON `status=ok`;
- stable endpoint: `/api/updates/windows/stable`;
- pre-publication stable response: HTTP `503`, JSON `status=manifest_not_published`;
- response cache policy: `Cache-Control: no-store`;
- pre-publication retry hint: `Retry-After: 3600`;
- latest deployment verified during Step 10A: Cloudflare Worker version ID `ec2f165e-6533-444e-a67b-ae5383fdfb15`.

Security design:
- the Worker receives no ChitLog finance data;
- the Worker has no ChitLog user database, D1, KV, R2, login, cookies, or application credentials;
- the production Ed25519 private key and passphrase are never stored in Cloudflare;
- Step 11 will publish only an already-signed public manifest;
- unknown routes fail with `404`;
- unsupported HTTP methods fail with `405`;
- query strings are rejected;
- the release endpoint remains fail-closed until a signed manifest exists.

Step 10A live verification on Windows:
- health endpoint: HTTP `200 application/json`;
- stable endpoint: HTTP `503 application/json`;
- state: `manifest_not_published`;
- cache: `no-store`;
- retry-after: `3600`;
- result: PASS.

#### Step 10B — Application endpoint wiring

Base repository HEAD: `87e8b99`
Implementation commit: `c2bad74` — `feat: configure production update endpoint`
Remote status: pushed to `origin/feature/auto-updater`
Checkpoint status: implementation committed and pushed.

Application policy:
- Stable channel is pinned to `https://chitlog-updates.chitlogapp.workers.dev/api/updates/windows/stable`;
- Beta remains deliberately unconfigured until a separate Beta endpoint exists;
- Beta never falls back to Stable metadata;
- users cannot supply arbitrary update-service URLs through update preferences;
- existing TLS verification, no-redirect transport, response-size limits, signed-manifest verification, and installer hash verification remain unchanged.

Windows verification completed before commit:
- dedicated Step 10B endpoint-configuration tests: `8 passed in 0.21s`;
- focused Step 1/3/4/10B updater regression group: `95 passed in 3.53s`;
- live check through ChitLog's own restricted HTTPS transport: PASS;
- live transport reached `https://chitlog-updates.chitlogapp.workers.dev/api/updates/windows/stable` with normal TLS/hostname verification;
- live endpoint returned the expected fail-closed HTTP `503` while the manifest remains unpublished;
- no signed manifest was consumed or trusted during the live transport check;
- complete application suite: `733 passed, 2 skipped in 46.16s`;
- `python -m chitlog.core.security_audit`: `CHITLOG SECURITY REVIEW: PASS`;
- security audit found no forbidden script execution, broad network client, embedded web engine, hard-coded credential literal, developer path, SQL trace, or deferred Google Drive module;
- `git diff --check`: no errors; Windows emitted only normal LF-to-CRLF conversion notices;
- reviewed tracked Step 10B scope:
  - modified `chitlog/core/update_config.py`;
  - modified `chitlog/ui/startup_update_scheduler.py`;
  - modified `chitlog/ui/update_check_runner.py`;
  - modified `docs/ChitLog_AutoUpdater_Build_Guide.md`;
  - modified `tests/test_auto_updater_step1.py`;
  - modified `tests/test_auto_updater_step3_checker.py`;
  - modified `tests/test_auto_updater_step4_manual_check.py`;
  - added `tests/test_auto_updater_step10_endpoint_config.py`.

Acceptance conclusion:
Step 10 establishes a live, dedicated, fail-closed Cloudflare update service and wires the Stable application channel to its exact HTTPS manifest route without weakening ChitLog's TLS, no-redirect, signed-manifest, installer-size, or SHA-256 verification boundaries. Beta remains deliberately unconfigured rather than inheriting Stable metadata, and normal accounting remains independent of update-service availability.

Custom-domain note:
The `workers.dev` endpoint is the verified bootstrap origin. If a ChitLog `.xyz` custom domain is purchased before final release, the final application build should pin the chosen custom update hostname directly rather than rely on redirects. Existing released clients must retain access to whatever hostname they were built to use.

---

## Completed Step 11A Checkpoint

### Step 11 — Release / Signing Tooling

#### Step 11A — Deterministic Offline Release Signer

Base repository HEAD: `8ffd4fb`
Implementation commit: `9b308b2` — `build: add offline release manifest signer`
Remote status: pushed to `origin/feature/auto-updater`
Checkpoint status: implementation committed and pushed.

Purpose:
- sign only the exact final NSIS installer produced by the existing ChitLog build pipeline;
- keep all production private-key use outside the runtime `chitlog` package;
- require the encrypted PKCS#8 Ed25519 private key to remain outside the Git repository;
- request the private-key passphrase interactively without echo and never accept it as a command-line argument;
- derive the public key from the loaded private key and require an exact match to ChitLog's embedded production trust anchor before signing;
- compute installer SHA-256/size locally and require the existing `build_installer.ps1` hash file to match;
- construct the release payload through the same strict `UpdateManifestPayload` model used by runtime verification;
- use an explicit `published_at` value so identical release inputs create identical Ed25519/JSON output;
- immediately strict-parse and Ed25519-verify the generated manifest before writing public artifacts;
- write only public manifest/hash/release metadata beneath the ignored `release/` directory.

Security boundaries:
- no private key or passphrase is stored in source, Cloudflare, release output, or command-line arguments;
- no network client is used by the signer;
- the signer refuses a private key stored inside the repository;
- unencrypted private keys are rejected;
- the signer refuses to sign an arbitrary executable path and binds to `release/ChitLog-<APP_VERSION>-Setup.exe`;
- the direct installer URL must end with the exact release installer filename and must not use a query string;
- actual production signing is deferred until the final installer and final direct HTTPS hosting URL are ready.

Files:
- new `packaging/create_signed_update_manifest.py`;
- new `packaging/sign_release_manifest.ps1`;
- new `tests/test_auto_updater_step11_release_signing.py`;
- updated cumulative build guide.

Windows verification completed before commit:
- dedicated Step 11A signer tests: `11 passed in 0.42s`;
- focused Step 2 manifest/signature/packaging + Step 9 production trust + Step 11A signer regressions: `82 passed in 0.58s`;
- complete application suite: `744 passed, 2 skipped in 46.55s`;
- `python -m chitlog.core.security_audit`: `CHITLOG SECURITY REVIEW: PASS`;
- security audit found no forbidden script execution, broad network client, embedded web engine, hard-coded credential literal, developer path, SQL trace, or deferred Google Drive module;
- `git diff --check`: no errors; Windows emitted only the normal LF-to-CRLF conversion notice for the build guide;
- reviewed Step 11A working-tree scope:
  - added `packaging/create_signed_update_manifest.py`;
  - added `packaging/sign_release_manifest.ps1`;
  - added `tests/test_auto_updater_step11_release_signing.py`;
  - modified `docs/ChitLog_AutoUpdater_Build_Guide.md`.

Acceptance conclusion:
Step 11A provides deterministic, packaging-only offline manifest signing machinery without moving production private-key material into the runtime application, repository, command line, Cloudflare, or release metadata. The signer binds to the exact release installer path and build hash, validates the strict runtime manifest schema, proves the private key matches ChitLog's embedded production public trust anchor, and re-verifies generated public output before writing it. Actual production signing remains intentionally deferred until Step 11B, after the final post-Step-10 installer and direct HTTPS installer URL are fixed.

Important:
Step 11A tests use ephemeral test Ed25519 keys only. The production private key is not required for this implementation checkpoint and should not be copied into the repository for testing.

#### Step 11A Follow-Up — Fail-Closed Path Validation Hardening

Initial signer implementation:
- `9b308b2` — `build: add offline release manifest signer`

Initial documentation checkpoint:
- `ac028ed` — `docs: record Step 11A checkpoint`

Follow-up security implementation:
- `3fbc4fb` — `security: harden release signer path validation`
- pushed to `origin/feature/auto-updater`

Reason for the follow-up:
- the initial signer resolved the expected installer path before checking `is_symlink()`;
- `Path.resolve()` follows a symbolic link, so the later symlink check observed the resolved target instead of the lexical installer path;
- the private-key loader had the same ordering issue: it resolved the private-key path before the symlink rejection;
- this weakened the intended fail-closed path-validation boundary even though the remaining installer/hash/signature checks still existed.

Hardening applied:
- installer lexical path is checked for `is_symlink()` before `resolve(strict=True)`;
- private-key lexical path is checked for `is_symlink()` before `resolve(strict=True)`;
- the resolved installer is required to remain within the ChitLog repository;
- deterministic regression tests prove `resolve()` is not called for a symlink candidate;
- no production private key or passphrase was accessed during this hardening checkpoint.

Windows verification completed before the hardening commit:
- dedicated Step 11A release-signing tests: `13 passed in 0.43s`;
- focused Step 2 manifest/signature/packaging + Step 9 production trust + Step 11A release-signing group: `84 passed in 0.61s`;
- complete application suite: `746 passed, 2 skipped in 44.70s`;
- `python -m chitlog.core.security_audit`: `CHITLOG SECURITY REVIEW: PASS`;
- `git diff --check`: no errors; Windows emitted only normal LF-to-CRLF conversion warnings;
- staged scope contained exactly:
  - `packaging/create_signed_update_manifest.py`;
  - `tests/test_auto_updater_step11_release_signing.py`;
- `git diff --cached --check`: clean;
- implementation commit pushed successfully.

Acceptance conclusion:
The Step 11A path-validation hardening issue was closed by commit `3fbc4fb`. The release signer rejects installer/private-key symlinks before path resolution, preserving the intended fail-closed semantics without changing the production Ed25519 trust anchor, manifest format, installer hash rules, or private-key handling model. A later production-use CLI launch issue was discovered and fixed separately by `cae99be`, as recorded below.

#### Step 11A Production CLI Follow-Up — Direct File-Path Import Bootstrap

Production-use discovery:
- after the final v1.1.0 installer, GitHub release, website publication, and redirect-free updater Worker installer route were prepared, the first real production signing attempt invoked `packaging/sign_release_manifest.ps1`;
- the PowerShell wrapper successfully reached the Python signer, but Python failed during module import with `ModuleNotFoundError: No module named 'chitlog'`;
- the failure occurred before the signer reached its passphrase prompt, before the Python signer loaded private-key contents, and before any manifest/public signing artifact was produced;
- the wrapper had already performed its normal file-existence check for the configured encrypted private-key path;
- no production manifest was published from this failed attempt.

Root cause:
- `sign_release_manifest.ps1` intentionally launches `packaging/create_signed_update_manifest.py` by file path;
- in that launch mode Python places the script directory (`packaging/`) at `sys.path[0]`, not the repository root;
- the signer imports trusted ChitLog runtime models such as `chitlog.core.update_config`, so the local `chitlog` package was not importable in this direct file-path execution mode;
- the earlier Step 11A tests imported the signer as a module and therefore did not exercise the exact wrapper/CLI launch mode that failed in production.

Implementation fix:
- implementation commit: `cae99be` — `fix: make release signer runnable by file path`;
- `packaging/create_signed_update_manifest.py` now derives the repository root from `Path(__file__).resolve().parents[1]`;
- that root is inserted into `sys.path` before the signer imports the local `chitlog` package;
- no production trust anchor, manifest schema, signing algorithm, installer hash rule, URL policy, private-key format, or passphrase-handling rule changed;
- a subprocess regression test launches the signer by absolute file path from an unrelated temporary working directory and requires `--help` to complete successfully.

Windows verification before the implementation commit:
- direct signer launch from outside the repository: exit code `0`;
- dedicated Step 11A release-signing tests: `14 passed in 0.56s`;
- `python -m chitlog.core.security_audit`: `CHITLOG SECURITY REVIEW: PASS`;
- `git diff --check`: no errors; Windows emitted only normal LF-to-CRLF conversion warnings;
- tracked implementation scope contained exactly:
  - `packaging/create_signed_update_manifest.py`;
  - `tests/test_auto_updater_step11_release_signing.py`;
- staged scope contained exactly those two files;
- `git diff --cached --check`: clean;
- implementation commit `cae99be` was pushed successfully to `origin/feature/auto-updater`;
- local and remote `feature/auto-updater` both resolved to `cae99be`;
- working tree was clean after the push.

Acceptance conclusion:
The production signer is now verified in the same direct file-path launch mode used by `sign_release_manifest.ps1`. The fix is limited to Python import-path bootstrapping and does not weaken ChitLog's signing, installer-integrity, or private-key security boundaries. Production signing should resume only after this documentation checkpoint is committed and pushed.

#### Step 11B Hosting / Zero-Budget Distribution Note

Project constraint:
- hosting/distribution remains `$0` except for the planned future purchase of a `.xyz` marketing domain;
- Cloudflare R2 was evaluated temporarily but abandoned before production deployment;
- production installer storage remains GitHub Releases.

Public release repository:
- repository: `ashan093/chitlog-releases`;
- visibility: public;
- v1.1.0 release/tag is published and is the first official supported downloadable/updater-enabled baseline;
- GitHub release page: `https://github.com/ashan093/chitlog-releases/releases/tag/v1.1.0`;
- installer asset: `ChitLog-1.1.0-Setup.exe`;
- installer asset URL: `https://github.com/ashan093/chitlog-releases/releases/download/v1.1.0/ChitLog-1.1.0-Setup.exe`;
- published timestamp: `2026-09-29T07:19:27Z`;
- installer size: `75,788,037 bytes`;
- installer SHA-256: `72beef698ff7eae97d260870d8d9c30a182dc9ccfa2c3aeb69b89efd1a79145b`;
- an independent public GitHub download was verified to match that exact size and SHA-256;
- the earlier v1.0.0 public release and tag were retired and removed; the old release page and installer URL were verified to return `404`;
- a private local v1.0.0 archive is retained separately for the developer, but v1.0.0 is not the production updater baseline.

Dedicated updater Worker:
- Worker name: `chitlog-updates`;
- stable origin remains `https://chitlog-updates.chitlogapp.workers.dev`;
- pre-manifest installer-proxy deployment version ID: `07c5d864-f5f9-4b79-a2ae-4bbb3cb3869c`;
- production signed-manifest deployment version ID: `084d3777-33f5-4878-8b6a-2a1208de0ae2`;
- immutable v1.1.0 installer proxy path:
  `https://chitlog-updates.chitlogapp.workers.dev/downloads/windows/stable/1.1.0/72beef698ff7eae97d260870d8d9c30a182dc9ccfa2c3aeb69b89efd1a79145b/ChitLog-1.1.0-Setup.exe`;
- the proxy follows the GitHub redirect server-side so ChitLog's restricted updater transport does not see a redirect;
- live installer `HEAD` returns HTTP `200`, `Content-Length: 75788037`, immutable cache policy, the exact installer filename, and no `Location` redirect;
- a full live proxy download matched `75,788,037 bytes` and SHA-256 `72beef698ff7eae97d260870d8d9c30a182dc9ccfa2c3aeb69b89efd1a79145b`;
- the production Stable manifest is now published at `/api/updates/windows/stable`;
- live manifest response: HTTP `200`, `Content-Type: application/json; charset=utf-8`, `Content-Length: 741`, `Cache-Control: no-store`, and no redirect;
- live production manifest SHA-256: `ee33023877139d94c76f1eb5ef1253c24f66a300eeb766d214e57b51c858cf0e`;
- no production private key, passphrase, finance data, R2 bucket, or application database is present in this Worker.
Marketing website:
- source repository: `ashan093/chitlog-site`;
- repository visibility: private;
- production website origin: `https://chitlog.chitlogapp.workers.dev/`;
- website release commit: `e34d3f4` — `release: publish ChitLog 1.1.0 website`;
- Cloudflare website Worker deployment version ID: `7dbc0bb9-d7d7-4254-93f3-23bd859eda4d`;
- live homepage/config advertise v1.1.0, `72.28 MiB`, and the exact production SHA-256;
- `POST /api/downloads/start` accepts v1.1.0 and returns the public GitHub v1.1.0 installer URL;
- the same API rejects retired v1.0.0 with HTTP `400`;
- downloading through the live website's returned URL produced exactly `75,788,037 bytes` and SHA-256 `72beef698ff7eae97d260870d8d9c30a182dc9ccfa2c3aeb69b89efd1a79145b`;
- browser downloads remain direct GitHub Release downloads; the marketing website Worker is not the updater binary proxy.

Endpoint separation:
- browser/site distribution: private `chitlog-site` source -> Cloudflare website Worker -> GitHub Releases download URL;
- application updater distribution: ChitLog -> dedicated `chitlog-updates` Worker -> server-side GitHub installer proxy;
- the updater must continue using the stable `workers.dev` endpoint already embedded in v1.1.0;
- a future `.xyz` marketing-domain migration must not silently replace or redirect the updater endpoint for already-released clients.

#### Step 11B — Production Signing and Stable Manifest Publication — Completed

Documentation baseline before this completion update:
- application repository HEAD: `90989fa` — `docs: record Step 11B publication state`;
- branch: `feature/auto-updater`;
- local and remote branch both resolved to `90989fa`;
- application working tree was clean before production signing and remained clean after publication verification.

Production signing inputs:
- release version: `1.1.0`;
- channel: `stable`;
- production key ID: `chitlog-update-2026-01`;
- production public-key SHA-256: `eeb2edd191b0074c318db350001491fd89e94801a087685a4223052ec2d0151b`;
- installer size: `75,788,037 bytes`;
- installer SHA-256: `72beef698ff7eae97d260870d8d9c30a182dc9ccfa2c3aeb69b89efd1a79145b`;
- installer URL:
  `https://chitlog-updates.chitlogapp.workers.dev/downloads/windows/stable/1.1.0/72beef698ff7eae97d260870d8d9c30a182dc9ccfa2c3aeb69b89efd1a79145b/ChitLog-1.1.0-Setup.exe`;
- release-notes URL: `https://github.com/ashan093/chitlog-releases/releases/tag/v1.1.0`;
- `published_at = 2026-09-29T07:19:27Z`;
- `minimum_supported_version = 1.1.0`;
- `mandatory = false`.

Production signer result:
- `packaging/sign_release_manifest.ps1` completed with `CHITLOG STEP 11A RELEASE MANIFEST SIGNING: PASS`;
- the encrypted production Ed25519 private key was loaded only by the local offline signer after an interactive non-echo passphrase prompt;
- the private key and passphrase were not written to release output and were not sent to GitHub or Cloudflare;
- generated manifest: `release/ChitLog-1.1.0-update-manifest.json`;
- generated manifest byte length: `741`;
- generated manifest SHA-256:
  `ee33023877139d94c76f1eb5ef1253c24f66a300eeb766d214e57b51c858cf0e`;
- generated manifest hash file and release metadata matched the exact manifest and installer values;
- the signer strict-parsed and Ed25519-verified its own output before writing the public release artifacts.

Independent local production-manifest verification:
- strict runtime parser accepted the exact generated bytes;
- production Ed25519 signature verification passed using ChitLog's embedded production trust registry;
- generated manifest SHA-256 matched the recorded hash file;
- release metadata matched the exact installer URL, installer size/hash, key ID, production public-key fingerprint, minimum supported version, and mandatory flag;
- ChitLog `1.1.0` evaluated the signed `1.1.0` manifest as `up_to_date`;
- no private-key or passphrase text was present in the public manifest/hash/metadata artifacts.

Cloudflare publication:
- only the already-signed PUBLIC production manifest was embedded into the dedicated `chitlog-updates` Worker;
- production private-key material and its passphrase were never Cloudflare inputs;
- Wrangler dry-run passed before deployment;
- signed-manifest production deployment completed successfully;
- Cloudflare Worker Version ID:
  `084d3777-33f5-4878-8b6a-2a1208de0ae2`;
- the deployment command itself succeeded before a local post-deployment helper encountered a Windows PowerShell compatibility issue.

Windows PowerShell verification-helper follow-up:
- the first post-deployment helper used `Invoke-WebRequest -SkipHttpErrorCheck`;
- the installed Windows PowerShell version does not support that parameter;
- this failure occurred after Cloudflare had already successfully deployed Version ID `084d3777-33f5-4878-8b6a-2a1208de0ae2`;
- the live Worker was not rolled back and did not need redeployment;
- the two local Worker verification helpers were corrected to use explicit `curl.exe` requests compatible with Windows PowerShell;
- the compatibility patch changed only `DEPLOY-AND-VERIFY.ps1` and `VERIFY-LIVE-ENDPOINT.ps1` in the local Worker working directory;
- no Cloudflare deployment was performed by the compatibility patch or its verifier.

Live production verification:
- `/healthz`: HTTP `200` with JSON `status=ok`;
- `/api/updates/windows/stable`: HTTP `200`;
- manifest `Content-Type`: `application/json; charset=utf-8`;
- manifest `Content-Length`: `741`;
- manifest cache policy: `Cache-Control: no-store`;
- manifest exposed no `Location` redirect;
- downloaded live manifest SHA-256 exactly matched:
  `ee33023877139d94c76f1eb5ef1253c24f66a300eeb766d214e57b51c858cf0e`;
- live manifest bytes were byte-for-byte identical to the locally signed production manifest;
- live production Ed25519 verification passed;
- live signed policy remained `version=1.1.0`, `minimum_supported_version=1.1.0`, `mandatory=false`;
- ChitLog's real `check_for_updates()` pipeline passed against the live endpoint using its restricted HTTPS transport, strict manifest parser, production Ed25519 trust anchor, and update-decision logic;
- real pipeline result for running ChitLog `1.1.0`: `up_to_date`;
- immutable installer proxy `HEAD`: HTTP `200`, exact `Content-Length: 75788037`, correct filename, and no redirect;
- application repository remained clean with local and remote `feature/auto-updater` both at `90989fa`.

Acceptance conclusion:
Step 11B production signing and publication is complete. The final v1.1.0 installer bytes are fixed, the signed Stable manifest is live from the dedicated `chitlog-updates` Worker, the live manifest is byte-identical to the locally signed artifact and verifies under ChitLog's production Ed25519 trust anchor, the application evaluates its own v1.1.0 release as up-to-date, and the redirect-free installer proxy still serves the exact signed installer metadata. The next release checkpoint is clean-VM acceptance; do not rebuild or replace the published v1.1.0 installer or mutate the signed v1.1.0 manifest in place.

---

## Remaining Production Work

### Step 12 — Clean VM Release Acceptance
ChitLog v1.1.0 is the first official supported updater-enabled baseline. The retired v1.0.0 build did not contain this updater and is therefore not used as the production automatic-update acceptance path.

On a clean disposable Windows VM:
- install the real public ChitLog v1.1.0 installer;
- verify setup, first-run authentication, lock/logout, shortcuts, uninstaller, and selected install path;
- create realistic disposable finance, worker, budget, liability, payment, and settings data;
- close/reopen and verify encrypted data/settings survive;
- verify update checks reach the live signed Stable manifest without exposing private finance data;
- verify the current v1.1.0 manifest is treated as up-to-date;
- exercise the full automatic upgrade path later with a controlled signed test release or the next real patch release so the path begins from v1.1.0;
- during that upgrade-path test, verify recovery snapshot, updater handoff, installer hash verification, elevation, in-place upgrade, relaunch, preserved database/settings, shortcuts/uninstaller, and absence of developer paths.
### Step 13 — Release Finalization
- resolve any blockers discovered during clean-VM acceptance;
- run the final full test/security/package provenance audit;
- merge the updater branch only after the release-acceptance evidence is complete;
- record the final application source commit/tag according to the release process;
- preserve the already-published v1.1.0 installer and signed manifest as immutable release artifacts;
- perform the final live update check from the actually installed/released v1.1.0 build.
