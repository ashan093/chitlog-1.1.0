"""Reusable layout-based cards, text, buttons, and branded background."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from chitlog.ui.theme import THEMES, SPACE, resolve_theme


def text_label(text: str, role: str = "", parent=None) -> QLabel:
    label = QLabel(text, parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("role", role)
    label.setWordWrap(True)
    return label


def button(text: str, role: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", glass: bool = False):
        super().__init__()
        self.setProperty("role", "glass" if glass else "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*([SPACE["lg"]] * 4))
        self.body.setSpacing(SPACE["md"])
        self.body.addWidget(text_label(title, "heading"))
        if subtitle:
            self.body.addWidget(text_label(subtitle, "muted"))


class Background(QWidget):
    """Theme artwork background with cached cover scaling.

    The original paint path performed a high-quality full-image scale on every
    repaint. Hovering controls, updating labels, scrolling, and other ordinary
    UI activity can all repaint the main window, so the same 1672x941 artwork
    was being resampled repeatedly even when the window size had not changed.
    """

    _MAX_CACHE_ENTRIES = 4

    def __init__(self, assets: Path):
        super().__init__()
        self.assets = assets
        self.theme_name = "light"
        self.artwork = {
            "light": QPixmap(str(assets / "chit_background_llight.png")),
            "dark": QPixmap(str(assets / "chit_background_dark.png")),
        }
        self._scaled_artwork_cache: dict[tuple[str, int, int], QPixmap] = {}

    def _cover_artwork(self, theme_key: str) -> QPixmap:
        source = self.artwork[theme_key]
        if source.isNull():
            return source

        width = max(1, self.width())
        height = max(1, self.height())
        cache_key = (theme_key, width, height)
        cached = self._scaled_artwork_cache.get(cache_key)
        if cached is not None:
            return cached

        # Keep exactly the same cover/aspect-ratio behavior as before; the only
        # change is that the expensive smooth result is reused on later paints.
        scaled = source.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        if len(self._scaled_artwork_cache) >= self._MAX_CACHE_ENTRIES:
            self._scaled_artwork_cache.clear()
        self._scaled_artwork_cache[cache_key] = scaled
        return scaled

    def paintEvent(self, event):
        theme_key = resolve_theme(self.theme_name)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(THEMES[theme_key].background))

        scaled = self._cover_artwork(theme_key)
        if not scaled.isNull():
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )

        overlay = QColor(THEMES[theme_key].background)
        overlay.setAlpha(160)
        painter.fillRect(self.rect(), overlay)

