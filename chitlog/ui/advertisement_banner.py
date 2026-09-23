"""Safe Step 21 advertisement banner placeholder.

This module intentionally contains NO network client, HTML renderer, JavaScript
engine, cookies, tracking, database access, or advertisement SDK.

Future versions may feed pre-approved content into AdvertisementBanner after a
separate security/privacy review.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from chitlog.ui.theme import SPACE
from chitlog.ui.widgets import button, text_label


MAX_AD_TEXT = 180
MAX_AD_IMAGE_BYTES = 2 * 1024 * 1024
MAX_AD_IMAGE_WIDTH = 1600
MAX_AD_IMAGE_HEIGHT = 600
MAX_AD_LINK_LENGTH = 2048
ALLOWED_IMAGE_FORMATS = frozenset({"png", "jpg", "jpeg", "webp"})


class AdvertisementValidationError(ValueError):
    """Rejected advertisement content that is unsafe or malformed."""


@dataclass(frozen=True)
class BannerContent:
    """Non-executable banner content.

    `image_bytes` must already be supplied by a trusted future content layer.
    This V1 placeholder never downloads it.
    """

    text: str
    image_bytes: bytes | None = None
    link_url: str | None = None


def _clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _validate_link(link_url: str | None, allowed_hosts: frozenset[str]) -> str | None:
    if link_url is None:
        return None

    link = (link_url or "").strip()
    if not link:
        return None
    if len(link) > MAX_AD_LINK_LENGTH:
        raise AdvertisementValidationError("Advertisement link is too long.")

    parts = urlsplit(link)
    host = (parts.hostname or "").lower()

    if parts.scheme.lower() != "https":
        raise AdvertisementValidationError(
            "Advertisement links must use HTTPS."
        )
    if not host:
        raise AdvertisementValidationError(
            "Advertisement link must contain a valid host."
        )
    if parts.username is not None or parts.password is not None:
        raise AdvertisementValidationError(
            "Advertisement links cannot contain embedded credentials."
        )
    if host not in allowed_hosts:
        raise AdvertisementValidationError(
            "Advertisement link host is not approved."
        )

    return link


def _decode_image(image_bytes: bytes | None) -> QPixmap | None:
    if image_bytes is None:
        return None
    if not isinstance(image_bytes, (bytes, bytearray)):
        raise AdvertisementValidationError(
            "Advertisement image must be binary image data."
        )

    payload = bytes(image_bytes)
    if not payload:
        return None
    if len(payload) > MAX_AD_IMAGE_BYTES:
        raise AdvertisementValidationError(
            "Advertisement image exceeds the allowed size."
        )

    buffer = QBuffer()
    buffer.setData(QByteArray(payload))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise AdvertisementValidationError(
            "Advertisement image could not be validated."
        )

    reader = QImageReader(buffer)
    image_format = bytes(reader.format()).decode("ascii", "ignore").lower()
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise AdvertisementValidationError(
            "Advertisement image format is not approved."
        )

    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise AdvertisementValidationError(
            "Advertisement image is invalid or corrupted."
        )
    if (
        image.width() <= 0
        or image.height() <= 0
        or image.width() > MAX_AD_IMAGE_WIDTH
        or image.height() > MAX_AD_IMAGE_HEIGHT
    ):
        raise AdvertisementValidationError(
            "Advertisement image dimensions are outside the allowed range."
        )

    return QPixmap.fromImage(image)


class AdvertisementBanner(QFrame):
    """Fixed-height, isolated advertisement container.

    The banner is collapsed by default. If content is supplied later, it uses a
    stable fixed height so switching between approved banners does not make the
    application jump around.
    """

    BANNER_HEIGHT = 72

    def __init__(
        self,
        parent=None,
        *,
        allowed_link_hosts: tuple[str, ...] = (),
    ):
        super().__init__(parent)
        self.setObjectName("advertisementBanner")
        self.setProperty("role", "card")
        self.setAccessibleName("Advertisement")
        self.setFixedHeight(self.BANNER_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self._allowed_hosts = frozenset(
            host.strip().lower()
            for host in allowed_link_hosts
            if host and host.strip()
        )
        self._link_url: str | None = None
        self._image_pixmap: QPixmap | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(
            SPACE["md"],
            SPACE["sm"],
            SPACE["md"],
            SPACE["sm"],
        )
        root.setSpacing(SPACE["md"])

        self.image_label = QLabel()
        self.image_label.setObjectName("advertisementImage")
        self.image_label.setFixedSize(QSize(96, 48))
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setVisible(False)
        root.addWidget(self.image_label)

        copy = QVBoxLayout()
        copy.setSpacing(2)

        self.disclosure_label = text_label("ADVERTISEMENT", "eyebrow")
        self.disclosure_label.setAccessibleName("Advertisement disclosure")
        copy.addWidget(self.disclosure_label)

        self.message_label = text_label("", "muted")
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.message_label.setWordWrap(True)
        copy.addWidget(self.message_label, 1)

        root.addLayout(copy, 1)

        self.link_button: QPushButton = button("Learn more")
        self.link_button.setProperty("compact", True)
        self.link_button.setAccessibleName("Open advertisement link")
        self.link_button.setToolTip(
            "Open the advertiser's approved HTTPS page in your system browser."
        )
        self.link_button.setVisible(False)
        self.link_button.clicked.connect(self._open_link)
        root.addWidget(
            self.link_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        # No ad content is bundled in V1, so the placeholder occupies no space.
        self.hide()

    @property
    def has_content(self) -> bool:
        return bool(self.message_label.text())

    def set_content(self, content: BannerContent) -> None:
        """Show validated non-executable banner content.

        No private ChitLog data is accepted or read by this component.
        """
        if not isinstance(content, BannerContent):
            raise AdvertisementValidationError(
                "Advertisement content has an invalid type."
            )

        message = _clean_text(content.text)
        if not message:
            raise AdvertisementValidationError(
                "Advertisement text is required."
            )
        if len(message) > MAX_AD_TEXT:
            raise AdvertisementValidationError(
                "Advertisement text is too long."
            )

        link = _validate_link(content.link_url, self._allowed_hosts)
        pixmap = _decode_image(content.image_bytes)

        self.disclosure_label.setText("ADVERTISEMENT")
        self.disclosure_label.setAccessibleName("Advertisement disclosure")
        self.message_label.setText(message)
        self._link_url = link
        self.link_button.setVisible(link is not None)

        self._image_pixmap = pixmap
        if pixmap is None:
            self.image_label.clear()
            self.image_label.setVisible(False)
        else:
            scaled = pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)
            self.image_label.setVisible(True)

        self.show()

    def show_local_test_preview(self) -> None:
        """Display a local, non-network test banner for layout verification.

        This is intentionally NOT a Google/AdMob ad. Native Windows PySide6 has
        no supported Google Mobile Ads SDK, so this preview lets us verify the
        banner placement without pretending that an unsupported integration is
        live.
        """
        self.set_content(
            BannerContent(
                text=(
                    "Preview only — this is ChitLog's local test advertisement "
                    "banner. No ad network request, tracking, or financial data "
                    "sharing is occurring."
                )
            )
        )
        self.disclosure_label.setText("TEST ADVERTISEMENT")
        self.disclosure_label.setAccessibleName("Test advertisement disclosure")

    def clear_content(self) -> None:
        """Remove banner content and collapse the placeholder."""
        self._link_url = None
        self._image_pixmap = None
        self.message_label.clear()
        self.image_label.clear()
        self.image_label.hide()
        self.link_button.hide()
        self.hide()

    def _open_link(self) -> None:
        """Open only the already-validated HTTPS URL after a deliberate click."""
        if not self._link_url:
            return
        QDesktopServices.openUrl(QUrl(self._link_url))
