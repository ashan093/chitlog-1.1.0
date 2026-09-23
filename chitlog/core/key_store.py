"""Windows Credential Manager only. No automatic or plaintext backend fallback."""
import secrets
import sys
from pathlib import Path

SERVICE = "ChitLog.Database.v1"
ACCOUNT = "local-database-key"


class KeyStorageError(RuntimeError):
    """Safe error text: never include credential values."""


def windows_backend():
    if sys.platform != "win32":
        raise KeyStorageError("This database checkpoint requires Windows Credential Manager.")
    try:
        from keyring.backends.Windows import WinVaultKeyring
        vault = WinVaultKeyring()
        vault.persist = "local machine"
        return vault
    except Exception:
        raise KeyStorageError("Windows Credential Manager is unavailable.") from None


def load_database_key(path: Path, backend=None) -> bytes:
    """Caller must hold the application lock during creation and initialization."""
    vault = windows_backend() if backend is None else backend
    try:
        value = vault.get_password(SERVICE, ACCOUNT)
        if value is None:
            if path.exists():
                raise KeyStorageError("The database exists but its Windows key is missing. No key was replaced.")
            value = secrets.token_hex(32)
            vault.set_password(SERVICE, ACCOUNT, value)
            if vault.get_password(SERVICE, ACCOUNT) != value:
                raise KeyStorageError("Windows could not verify the saved database key.")
        if not isinstance(value, str) or len(value) != 64:
            raise KeyStorageError("The saved database key is invalid. No key was replaced.")
        try:
            key = bytes.fromhex(value)
        except ValueError:
            raise KeyStorageError("The saved database key is invalid. No key was replaced.") from None
        if len(key) != 32:
            raise KeyStorageError("The saved database key is invalid. No key was replaced.")
        return key
    except KeyStorageError:
        raise
    except Exception:
        raise KeyStorageError("Windows Credential Manager could not read or save the database key.") from None
