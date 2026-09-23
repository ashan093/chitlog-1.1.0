"""Small validated appearance preference; never store secrets here."""
import json
import os
from pathlib import Path
import tempfile

THEMES = ("light", "dark", "system")


class AppearanceSettings:
    def __init__(self, path: Path):
        self.path = path

    def load_theme(self, default: str = "light") -> str:
        """Load a saved theme, using the supplied valid fallback on failure."""
        if default not in THEMES:
            default = "light"
        try:
            if self.path.stat().st_size > 4096:
                return default
            value = json.loads(self.path.read_text(encoding="utf-8"))
            theme = value.get("theme") if isinstance(value, dict) else None
            return theme if theme in THEMES else default
        except (OSError, ValueError, UnicodeError):
            return default

    def save_theme(self, theme: str) -> None:
        if theme not in THEMES:
            raise ValueError("Unsupported theme")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".appearance-",
                delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump({"version": 1, "theme": theme}, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
