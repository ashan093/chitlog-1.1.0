# ChitLog Step 24 â€” Windows Packaging

This release configuration builds ChitLog 1.1.0 for 64-bit Windows using PyInstaller one-folder mode, then optionally wraps that folder in an NSIS installer.

## Release policy

- Build only from the locked Step 23 baseline.
- Build with Python 3.14.x x64.
- Run the full pytest suite and `chitlog.core.security_audit` before packaging.
- Do not put credentials, user databases, logs, backups, OAuth files, or signing secrets in the project or release payload.
- Use PyInstaller one-folder mode so LGPL-covered Qt shared libraries remain separate/replaceable.
- Ship `EULA.txt`, `THIRD_PARTY_NOTICES.txt`, `QT_LGPL_COMPLIANCE.txt`, and the generated `LICENSES` directory with every release.
- Do not delete ChitLog user data during uninstall.

## Build environment

From the project root in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
python -m pip check
```

## Build the portable Windows release

```powershell
.\packaging\build_windows.ps1
```

Expected outputs:

- `dist\ChitLog\ChitLog.exe`
- `dist\ChitLog\EULA.txt`
- `dist\ChitLog\THIRD_PARTY_NOTICES.txt`
- `dist\ChitLog\QT_LGPL_COMPLIANCE.txt`
- `dist\ChitLog\LICENSES\...`
- `release\ChitLog-1.1.0-windows-x64-portable.zip`
- SHA-256 files in `release`

## Build the installer

Install NSIS on the build PC and make `makensis.exe` available on PATH or install it in the normal NSIS Program Files directory.

Then run:

```powershell
.\packaging\build_installer.ps1
```

Expected output:

- `release\ChitLog-1.1.0-Setup.exe`
- `release\ChitLog-1.1.0-Setup.sha256.txt`

The installer displays `EULA.txt` and requires acceptance before installation.

## Clean-machine acceptance test

Test on a clean Windows 10/11 x64 machine or VM that does not have Python installed:

1. Run `ChitLog-1.1.0-Setup.exe`.
2. Confirm the EULA appears and installation does not require Python.
3. Confirm the Start menu shortcut and optional Desktop shortcut use the ChitLog icon.
4. Complete first-run setup, close ChitLog, reopen it, and log in.
5. Verify Transactions, Budget, Liabilities, Workers, Reports, Settings, PDF slips, reminders, and local backup/restore.
6. Confirm Light/Dark/System themes and supplied images load.
7. Confirm data is stored outside the installation directory.
8. Uninstall ChitLog and confirm the program is removed while user financial data remains intact.
9. Reinstall ChitLog and confirm the existing data can still be opened with the same Windows user profile/credential store.
10. Verify `EULA.txt`, `THIRD_PARTY_NOTICES.txt`, `QT_LGPL_COMPLIANCE.txt`, and `LICENSES` are installed beside ChitLog.

Do not publish the installer until this clean-machine test passes.
