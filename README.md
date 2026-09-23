# CHITLOG — STEP 3: SECURE DATABASE FOUNDATION

## Goal

Add an encrypted SQLite-compatible database, OS-protected key storage, schema
versioning, transactional migrations, and encrypted migration recovery snapshots.
Step 2 was confirmed working. Its theme preview remains available in this checkpoint.

## What we are building

Normal Windows launch now initializes or opens `%LOCALAPPDATA%\ChitLog\data\chitlog.db`
(actual location follows Qt's OS path selection). The initial database contains
only the migration history table, at schema version 1. No financial tables, login,
setup wizard, or sample financial data are created.

### Encryption and compatibility decision

- `sqlcipher3==0.6.2` publishes a standard CPython 3.14 Windows x86-64 wheel.
  That exact wheel was downloaded during compatibility checks; no local compiler
  or custom encryption wrapper is needed.
- The tested Linux wheel reports SQLCipher `4.12.0 community` / SQLite `3.51.1`.
  The binding version is not the embedded engine version. The Windows command
  below prints the actual engine shipped in your Windows wheel.
- `keyring==25.7.0` is used through its explicit `WinVaultKeyring` backend, with
  local-machine persistence. No automatic backend selection or plaintext fallback.
- Normal database startup is intentionally Windows-only at this checkpoint.
  Headless Linux tests use real SQLCipher with temporary random test keys.
- The compiled engine is a pinned development dependency, not a claim that it is
  the newest SQLCipher core. Engine/security-update and Windows packaging review
  remain required before a production release.

Sources checked 15 September 2026:
- https://pypi.org/project/sqlcipher3/0.6.2/
- https://pypi.org/project/keyring/25.7.0/
- https://www.zetetic.net/sqlcipher/sqlcipher-api/

### Protection boundaries

A cryptographically random 32-byte key is held in Windows Credential Manager under
service `ChitLog.Database.v1`, account `local-database-key`. It is not saved in JSON,
source, logs, or database fields. An existing database with a missing/invalid key
fails closed; ChitLog does not replace that key or reset the database.

Copying the database file alone does not reveal its contents. Database pages and
migration snapshots are encrypted by SQLCipher. Journal mode is DELETE with FULL
synchronization; temp storage is in memory. Foreign keys are enforced, extension
loading is disabled, and trusted-schema mode is disabled. No SQL trace logging.

The database is decrypted in application memory while open. This does not protect
against malware or another process already running with your Windows user's
privileges. Login/PIN gating arrives in the later setup/security steps. Appearance
preferences and fixed-event application logs remain unencrypted and contain no
financial data. Filenames and file sizes are visible to the OS.

Do not remove the Windows credential or manually delete/replace the database.
Losing the OS-held key can make the database unrecoverable. The user-portable,
password-protected backup/recovery feature is a later step. Internal migration
snapshots use the same Windows-held key and are NOT portable backup files.

### Database behavior

- One application instance per user-data folder prevents key-creation races.
- Every connection verifies SQLCipher presence and actually reads the database
  after applying the key; setting a key alone is not treated as successful access.
- Native SQLCipher page integrity, SQLite structure, and foreign keys are checked.
- Trusted ordered migrations use parameterized data inserts and one transaction.
- Existing schemas receive a unique encrypted, validated native-backup snapshot
  before migration. A failed snapshot prevents the migration from starting.
- A failed migration rolls back schema and version changes. Reopening does not
  reapply completed migrations. Unknown/newer schemas are rejected.
- Snapshots refuse active transactions and never overwrite an earlier file.
- Initial schema creation needs no pre-migration snapshot. No migration snapshot
  should appear on an ordinary fresh Step 3 launch.

## Files / Code

All files contain complete code. No manual line edits are required.

| File | Responsibility |
| --- | --- |
| chitlog/core/key_store.py | Explicit Windows vault and validated key creation/retrieval |
| chitlog/data/database.py | SQLCipher connection, integrity, transaction, snapshot lifecycle |
| chitlog/data/migrations.py | Version 1, identity checks, ordered transactional migration runner |
| chitlog/data/__init__.py | Data package |
| chitlog/application.py | Single-instance lock and database startup/shutdown/check command |
| chitlog/core/config.py | Version 0.3.0 |
| requirements.txt | Adds SQLCipher and Windows-only keyring |
| tests/test_database.py | Encryption, tamper, transaction, migration, key-store tests |
| tests/test_foundation.py | Keeps visual subprocess test explicitly separate from DB access |
| README.md | Installation, verification, security boundaries, checkpoint |

The archive retains all Step 1/2 code, tests, original images, themes, and preferences.
It contains no database, key, credential, log, virtual environment, or backup.

## Installation / Commands

Close all ChitLog windows. Extract the ZIP into a temporary folder, then copy the
CONTENTS of its `ChitLog` folder into your existing project folder containing
`app.py`. Replace matching files; keep your existing `.venv`.

In PowerShell in the project folder:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Use your confirmed Python 3.14.7 64-bit environment. If installation fails, paste
the error; do not substitute similarly named SQLCipher packages or build from source.

## How to run

First initialize/validate storage from the command line:

```powershell
.\.venv\Scripts\python.exe app.py --check-database
$LASTEXITCODE
```

Expected: SQLCipher version, schema version 1, Integrity OK, Windows Credential
Manager, database encryption enabled, and exit code 0. Run it again to confirm
reopening works. No key value is printed.

Then open the application:

```powershell
.\.venv\Scripts\python.exe app.py
```

## Expected result

Your familiar themed component preview opens with title
`ChitLog — Secure Database Foundation`. Its initial footer says
`Encrypted database ready • Schema 1 • Windows key storage`.
The visible components remain samples; Step 3 is a backend checkpoint.
Light/Dark switching and saved theme behavior are preserved.

## Tests

- Run `--check-database` twice and confirm both runs exit with 0.
- Open the window, check themes, close, and reopen.
- While one window is open, starting a second instance should give a clear message
  without opening another database session. Close that message, then the first window.
- Use `--show-paths` to confirm storage stays outside the project folder.
- Do NOT manually corrupt the real database or delete its key to test failures:
  the automated tests use disposable databases for those cases.

## Automated Tests

With all ChitLog windows closed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe app.py --smoke-test
$LASTEXITCODE
```

Expected on Windows: **32 passed**, then **0**. The Windows test creates a uniquely
named disposable Credential Manager entry, verifies it, and removes it; it does not
change the real ChitLog key. Ordinary smoke test exercises real Windows DB startup.

Tests cover copied-file rejection with plain SQLite and wrong keys, tamper rejection,
reopening, SQL-like strings stored as data, transaction rollback, foreign keys,
nested-transaction rejection, encrypted snapshot reopening, snapshot name collision,
migration success/failure/idempotence, backup failure preventing migration, newer or
inconsistent schemas, and missing/invalid/unavailable key storage. All earlier tests
remain included.

Developer visual-only option (does not validate database security):

```powershell
.\.venv\Scripts\python.exe app.py --preview-only
```

This mode has no database access and explicitly says so. It is used by the Linux
visual smoke test. It must not be substituted for the Windows acceptance commands.

## Builder verification

Linux/Python 3.12.14: **31 passed, 1 skipped**. The skipped test requires real Windows
Credential Manager. Actual SQLCipher encryption, copied-file rejection, integrity,
transactions, and migration snapshots were tested. Dependency consistency and
visual-only startup passed. Native Windows/Python 3.14.7 startup and credential
storage remain your acceptance checkpoint, not a claim of a completed Windows test.

## Checkpoint

STOP here. Reply `Step 3 works` with the `--check-database` output and test result,
or paste any error. Per the master prompt, Step 4 (First-Run Setup) starts only
after confirmation. No production-readiness claim is made at this stage.
