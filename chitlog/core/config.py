"""Application constants and OS-selected per-user directories."""
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryFile
from PySide6.QtCore import QStandardPaths

APP_NAME = "ChitLog"
from chitlog.core.version import APP_VERSION
ASSETS = Path(__file__).resolve().parents[2] / "assets"


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    def ensure(self) -> None:
        """Create and check directories without overwriting existing files."""
        if not self.root.is_absolute():
            raise ValueError("Application data path must be absolute.")
        for folder in (self.root, self.data, self.logs, self.backups, self.cache):
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            with TemporaryFile(dir=folder) as probe:
                probe.write(b"ChitLog directory check")
                probe.flush()


def default_paths() -> AppPaths:
    """Call after QApplication metadata is set; never fall back to the project."""
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not location:
        raise OSError("No local application data directory is available.")
    return AppPaths(Path(location))
