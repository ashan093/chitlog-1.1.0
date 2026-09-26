"""Step 6 main application shell with responsive sidebar navigation."""
from __future__ import annotations
from chitlog.ui.step23_polish import apply_step23_polish

import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QAbstractScrollArea,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chitlog.core.config import APP_NAME, ASSETS
from chitlog.core.settings import AppearanceSettings, THEMES as APPEARANCE_THEMES
from chitlog.ui.pages.dashboard import DashboardPage
from chitlog.ui.pages.budget import BudgetPage
from chitlog.ui.pages.liabilities import LiabilitiesPage
from chitlog.ui.pages.reports import ReportsPage
from chitlog.ui.pages.settings import SettingsPage
from chitlog.ui.pages.notifications import NotificationsPage
from chitlog.ui.pages.placeholders import create_placeholder_page
from chitlog.ui.pages.transactions import TransactionsPage
from chitlog.ui.pages.workers import WorkersPage
from chitlog.ui.theme import SCOOTER, SAPPHIRE, SPACE, resolve_theme, stylesheet
from chitlog.ui.widgets import Background, button, text_label
from chitlog.ui.advertisement_banner import AdvertisementBanner
from chitlog.ui.notification_controller import DesktopNotificationController
from chitlog.ui.update_notification_banner import UpdateNotificationBanner


NAV_ITEMS = (
    ("Dashboard", "dashboard"),
    ("Transactions", "transactions"),
    ("Budget", "budget"),
    ("Liabilities", "liabilities"),
    ("Workers", "workers"),
    ("Reports", "reports"),
    ("Settings", "settings"),
)


# Minimum content height before a page starts using its own outer vertical
# scrollbar. These values protect dense layouts from shrinking into overlaps
# on short windows, while leaving roomy windows uncluttered.
PAGE_SCROLL_MIN_HEIGHTS = {
    "Dashboard": 560,
    "Transactions": 660,
    "Budget": 620,
    "Liabilities": 640,
    "Workers": 700,
    "Reports": 640,
    "Settings": 820,
}


def _menu_icon() -> QIcon:
    """Crisp hamburger icon that does not depend on font glyph sizing."""
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(
        QPen(
            QColor(SCOOTER),
            2.2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    for y in (8, 14, 20):
        painter.drawLine(6, y, 22, y)
    painter.end()
    return QIcon(pixmap)


def _lock_icon() -> QIcon:
    """Small dependency-free padlock icon for the session Lock action."""
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(
        QPen(
            QColor(SCOOTER),
            2.1,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(6, 12, 16, 11), 2.5, 2.5)
    painter.drawArc(QRectF(9, 4, 10, 15), 0 * 16, 180 * 16)
    painter.drawLine(14, 16, 14, 19)
    painter.end()
    return QIcon(pixmap)


def _nav_icon(kind: str) -> QIcon:
    """Create small, dependency-free line icons for the collapsed sidebar."""
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(SCOOTER), 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if kind == "dashboard":
        for rect in (QRectF(4, 4, 8, 8), QRectF(16, 4, 8, 8), QRectF(4, 16, 8, 8), QRectF(16, 16, 8, 8)):
            painter.drawRoundedRect(rect, 2, 2)

    elif kind == "transactions":
        painter.drawLine(5, 9, 21, 9)
        painter.drawLine(18, 6, 22, 9)
        painter.drawLine(18, 12, 22, 9)
        painter.drawLine(23, 19, 7, 19)
        painter.drawLine(10, 16, 6, 19)
        painter.drawLine(10, 22, 6, 19)

    elif kind == "budget":
        painter.drawRoundedRect(QRectF(4, 7, 20, 15), 3, 3)
        painter.drawLine(7, 7, 19, 4)
        painter.drawRoundedRect(QRectF(16, 12, 8, 6), 2, 2)
        painter.drawPoint(QPointF(19, 15))

    elif kind == "liabilities":
        painter.drawEllipse(QRectF(4, 8, 10, 10))
        painter.drawEllipse(QRectF(14, 10, 10, 10))
        painter.drawLine(11, 13, 17, 15)

    elif kind == "workers":
        painter.drawEllipse(QRectF(9, 4, 10, 10))
        painter.drawArc(QRectF(5, 13, 18, 12), 20 * 16, 140 * 16)
        painter.drawEllipse(QRectF(2, 8, 6, 6))
        painter.drawEllipse(QRectF(20, 8, 6, 6))

    elif kind == "reports":
        painter.drawLine(4, 23, 24, 23)
        painter.drawRoundedRect(QRectF(5, 14, 4, 9), 1, 1)
        painter.drawRoundedRect(QRectF(12, 9, 4, 14), 1, 1)
        painter.drawRoundedRect(QRectF(19, 5, 4, 18), 1, 1)

    elif kind == "settings":
        painter.drawEllipse(QRectF(9, 9, 10, 10))
        painter.drawEllipse(QRectF(12, 12, 4, 4))
        center = QPointF(14, 14)
        for dx, dy in ((0, -10), (0, 10), (-10, 0), (10, 0), (-7, -7), (7, -7), (-7, 7), (7, 7)):
            painter.drawLine(center, QPointF(14 + dx, 14 + dy))

    painter.end()
    return QIcon(pixmap)


class NavButton(QToolButton):
    """Sidebar navigation button with an optional small numeric badge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.badge = QLabel("", self)
        self.badge.setProperty("role", "navBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.badge.hide()

    def set_badge_count(self, count: int) -> None:
        count = max(0, int(count))
        if count == 0:
            self.badge.hide()
            self.setAccessibleDescription("")
            return
        shown = "99+" if count > 99 else str(count)
        self.badge.setText(shown)
        # Keep badge geometry deterministic. Recalculating from sizeHint after
        # navigation/theme repolish could make a one-digit badge change from a
        # circle into a small oval even though its count had not changed.
        if count <= 9:
            badge_width = 20
        elif count <= 99:
            badge_width = 26
        else:
            badge_width = 32
        self.badge.setFixedSize(badge_width, 20)
        self.badge.show()
        self.badge.raise_()
        self.setAccessibleDescription(f"{count} open liabilities")
        self._position_badge()
        # The first count can be applied before the sidebar layout has assigned
        # the navigation button its final width. Reposition once more after Qt
        # completes that event-loop layout pass so the badge starts at the
        # right edge instead of briefly appearing at the upper-left corner.
        QTimer.singleShot(0, self._position_badge)

    def _position_badge(self) -> None:
        if not self.badge.isVisible():
            return
        x = max(2, self.width() - self.badge.width() - 7)
        if self.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly:
            y = 3
        else:
            y = max(2, (self.height() - self.badge.height()) // 2)
        self.badge.move(x, y)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_badge()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._position_badge)


class MainWindow(Background):
    """Main desktop shell. Step 6 contains navigation only, not finance logic."""

    # The application layer owns authentication.  The shell only emits this
    # request so locking never couples finance UI code to credential storage.
    lock_requested = Signal()

    EXPANDED_SIDEBAR_WIDTH = 236
    COLLAPSED_SIDEBAR_WIDTH = 76

    def __init__(
        self,
        assets: Path = ASSETS,
        settings: AppearanceSettings | None = None,
        theme_saver=None,
        transaction_service=None,
        dashboard_service=None,
        budget_service=None,
        liability_service=None,
        report_service=None,
        notification_service=None,
        backup_service=None,
        settings_service=None,
        update_preferences_service=None,
        update_check_runner=None,
        lazy_pages: bool = False,
        worker_service=None,
        currency_code: str = "LKR",
        currency_symbol: str = "Rs",
        worker_work_service=None,
        worker_payment_service=None,
        worker_payroll_service=None,
    ):
        super().__init__(assets)
        self.settings = settings
        self.theme_saver = theme_saver
        self.transaction_service = transaction_service
        self.dashboard_service = dashboard_service
        self.budget_service = budget_service
        self.liability_service = liability_service
        self.report_service = report_service
        self.notification_service = notification_service
        self.backup_service = backup_service
        self.settings_service = settings_service
        self.update_preferences_service = update_preferences_service
        self.update_check_runner = update_check_runner
        self.lazy_pages = bool(lazy_pages)
        self._lazy_unloaded_pages: set[str] = set()
        self._freshly_built_pages: set[str] = set()
        self.worker_service = worker_service
        self.worker_work_service = worker_work_service
        self.worker_payment_service = worker_payment_service
        self.worker_payroll_service = worker_payroll_service
        self.currency_code = currency_code
        self.currency_symbol = currency_symbol
        self.sidebar_collapsed = False
        self.setWindowTitle(APP_NAME)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(900, 480)
        self._set_safe_initial_size()

        root = QHBoxLayout(self)
        root.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
        root.setSpacing(SPACE["md"])

        self.sidebar = QFrame()
        self.sidebar.setProperty("role", "glass")
        self.sidebar.setFixedWidth(self.EXPANDED_SIDEBAR_WIDTH)
        self.sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(SPACE["sm"] + 4, SPACE["sm"] + 4, SPACE["sm"] + 4, SPACE["sm"] + 4)
        sidebar_layout.setSpacing(SPACE["sm"])

        self.brand_row_widget = QWidget()
        brand_row = QHBoxLayout(self.brand_row_widget)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(SPACE["sm"])

        self.logo_plate = QFrame()
        self.logo_plate.setObjectName("logoPlate")
        self.logo_plate.setFixedSize(46, 46)
        logo_layout = QVBoxLayout(self.logo_plate)
        logo_layout.setContentsMargins(5, 5, 5, 5)
        logo = QLabel(APP_NAME)
        pixmap = QPixmap(str(assets / "chit.png"))
        if not pixmap.isNull():
            small = pixmap.scaled(
                36,
                36,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(small)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setWindowIcon(QIcon(pixmap))
        else:
            logo.setStyleSheet(f"color: {SAPPHIRE}; font-weight: 700;")
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(logo)
        brand_row.addWidget(self.logo_plate)

        self.brand_text = QWidget()
        brand_text_layout = QVBoxLayout(self.brand_text)
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(0)
        brand_text_layout.addWidget(text_label("ChitLog", "heading"))
        brand_text_layout.addWidget(text_label("Personal Finance", "muted"))
        brand_row.addWidget(self.brand_text, 1)

        self.collapse_button = QToolButton()
        self.collapse_button.setProperty("role", "sidebarToggle")
        self.collapse_button.setIcon(_menu_icon())
        self.collapse_button.setIconSize(QSize(24, 24))
        # Expanded sidebar has more room, so give the toggle a comfortably
        # sized hit target. Collapsed mode intentionally remains more compact.
        self.collapse_button.setFixedSize(44, 44)
        self.collapse_button.setToolTip("Collapse sidebar")
        self.collapse_button.setAccessibleName("Collapse sidebar")
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.clicked.connect(self.toggle_sidebar)
        brand_row.addWidget(self.collapse_button)
        sidebar_layout.addWidget(self.brand_row_widget)
        sidebar_layout.addSpacing(SPACE["sm"])

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QToolButton] = {}
        for name, icon_name in NAV_ITEMS:
            nav = NavButton()
            nav.setProperty("role", "nav")
            nav.setText(name)
            nav.setIcon(_nav_icon(icon_name))
            nav.setIconSize(QSize(22, 22))
            nav.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            nav.setCheckable(True)
            nav.setAutoExclusive(True)
            nav.setMinimumHeight(40)
            nav.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            nav.setAccessibleName(f"Open {name}")
            nav.setToolTip(name)
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.clicked.connect(lambda checked=False, page=name: self.navigate(page))
            self.nav_group.addButton(nav)
            self.nav_buttons[name] = nav
            sidebar_layout.addWidget(nav)

        sidebar_layout.addStretch(1)

        self.lock_button = QToolButton()
        self.lock_button.setObjectName("sessionLockButton")
        self.lock_button.setProperty("role", "nav")
        self.lock_button.setText("Lock")
        self.lock_button.setIcon(_lock_icon())
        self.lock_button.setIconSize(QSize(22, 22))
        self.lock_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.lock_button.setMinimumHeight(40)
        self.lock_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.lock_button.setToolTip(
            "Lock ChitLog and require your PIN or password to continue."
        )
        self.lock_button.setAccessibleName("Lock ChitLog")
        self.lock_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lock_button.clicked.connect(self.lock_requested.emit)
        sidebar_layout.addWidget(self.lock_button)

        self.privacy_label = text_label("LOCAL • PRIVATE", "eyebrow")
        sidebar_layout.addWidget(self.privacy_label)
        self.sidebar_note = text_label("Core finance features work offline.", "muted")
        sidebar_layout.addWidget(self.sidebar_note)
        root.addWidget(self.sidebar)

        self.main_panel = QFrame()
        self.main_panel.setProperty("role", "glass")
        self.main_panel.setMinimumSize(0, 0)
        self.main_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["md"])
        main_layout.setSpacing(SPACE["md"])

        topbar = QHBoxLayout()
        topbar.setSpacing(SPACE["sm"])
        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        title_block.addWidget(text_label("CHITLOG", "eyebrow"))
        self.page_title = text_label("Dashboard", "heading")
        title_block.addWidget(self.page_title)
        topbar.addLayout(title_block)
        topbar.addStretch(1)

        self.appearance_label = text_label("APPEARANCE", "eyebrow")
        topbar.addWidget(self.appearance_label)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons: dict[str, QPushButton] = {}
        for name in ("light", "dark", "system"):
            choice = button(name.title())
            choice.setCheckable(True)
            choice.setAccessibleName(f"Use {name} theme")
            choice.clicked.connect(lambda checked=False, selected=name: self.select_theme(selected))
            self.theme_group.addButton(choice)
            self.theme_buttons[name] = choice
            topbar.addWidget(choice)
        main_layout.addLayout(topbar)

        # Global updater notice. It stays collapsed unless the shared secure
        # update runner returns a verified newer release.
        self.update_notification_banner = UpdateNotificationBanner(
            self.main_panel
        )
        main_layout.addWidget(self.update_notification_banner)

        if self.update_check_runner is not None:
            self.update_check_runner.succeeded.connect(
                self._secure_update_check_succeeded
            )

        self.notification_controller = (
            DesktopNotificationController(
                self.notification_service,
                self.windowIcon(),
                self,
            )
            if self.notification_service is not None
            else None
        )

        self.pages = QStackedWidget()
        self.pages.setMinimumSize(0, 0)
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.page_widgets: dict[str, QWidget] = {}
        self.page_containers: dict[str, QWidget] = {}
        self.page_scrolls: dict[str, QScrollArea] = {}
        for name, _icon_name in NAV_ITEMS:
            if self.lazy_pages and name != "Dashboard":
                # Keep post-login startup fast: only Dashboard is constructed
                # before the main window appears. The real page is built on
                # its first navigation.
                page = QWidget()
                page.setObjectName(
                    "lazyPage_" + name.lower().replace(" ", "_")
                )
                self._lazy_unloaded_pages.add(name)
            else:
                page = self._create_page(name)
                if self.lazy_pages:
                    self._freshly_built_pages.add(name)
            page.setMinimumSize(0, 0)
            self.page_widgets[name] = page

            # Every top-level page owns an independent outer viewport.
            #
            # IMPORTANT: the page itself is the QScrollArea widget; there is no
            # extra page-host layer. This avoids the recursive geometry behavior
            # from the earlier all-pages scroll experiment while still letting
            # dense pages scroll instead of overlap.
            page.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            page.setMinimumHeight(PAGE_SCROLL_MIN_HEIGHTS.get(name, 620))

            page_scroll = QScrollArea()
            page_scroll.setObjectName(
                "pageScroll_" + name.lower().replace(" ", "_")
            )
            page_scroll.setFrameShape(QFrame.Shape.NoFrame)
            page_scroll.setWidgetResizable(True)
            page_scroll.setSizeAdjustPolicy(
                QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
            )
            page_scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            page_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            page_scroll.setMinimumSize(0, 0)
            page_scroll.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            page_scroll.verticalScrollBar().setSingleStep(28)
            page_scroll.setWidget(page)

            self.page_scrolls[name] = page_scroll
            self.page_containers[name] = page_scroll
            self.pages.addWidget(page_scroll)
        if self.liability_service is not None:
            self._set_liability_badge(self.liability_service.totals().open_count)

        # Workers is now a single-page workspace. Keep a hidden compatibility
        # object for older helpers, but do not expose child navigation.
        self.worker_subtabs = QTabBar()
        self.worker_subtabs.setObjectName("workerFixedTabs")
        self.worker_subtabs.hide()

        worker_page = self.page_widgets.get("Workers")
        if isinstance(worker_page, WorkersPage):
            self._wire_worker_page(worker_page)

        # Historical compatibility aliases. content_scroll now starts as the
        # real Dashboard viewport; it is updated to the active page in navigate().
        self.content_scroll = self.page_scrolls["Dashboard"]

        self.content_host = QWidget()
        compatibility_layout = QVBoxLayout(self.content_host)
        compatibility_layout.setContentsMargins(0, 0, 14, 0)
        compatibility_layout.setSpacing(0)
        self.content_host.hide()

        main_layout.addWidget(self.pages, 1)

        # Step 21 safe advertisement slot. It is collapsed by default and
        # receives no database/service references. Future approved banner
        # content can be injected through its strict non-executable API.
        self.ad_banner = AdvertisementBanner(self.main_panel)
        # Development preview is opt-in only. Normal V1 startup keeps the
        # advertisement placeholder collapsed until a reviewed provider exists.
        if os.environ.get("CHITLOG_AD_PREVIEW", "").strip() == "1":
            self.ad_banner.show_local_test_preview()
        main_layout.addWidget(self.ad_banner)

        self.feedback = text_label(
            "Transactions are active in Step 7. Other finance modules remain placeholders.",
            "muted",
        )
        main_layout.addWidget(self.feedback)
        if self.notification_controller is not None:
            self.notification_controller.message.connect(self.feedback.setText)
            QTimer.singleShot(1000, self.notification_controller.start)
        root.addWidget(self.main_panel, 1)

        # When the saved preference is "system", Qt must re-apply the full
        # ChitLog stylesheet whenever Windows changes between Light and Dark.
        # Without this listener, only native/palette-painted areas repaint and
        # the existing QSS colors remain from the previous system scheme.
        self._system_style_hints = None
        self._connect_system_theme_updates()

        self.apply_theme(settings.load_theme() if settings else "light")
        self.navigate("Dashboard")
        QTimer.singleShot(0, self._update_responsive_buttons)
        apply_step23_polish(self)

    def _create_page(self, name: str) -> QWidget:
        """Construct one real top-level page and wire its page-specific signals."""
        if name == "Dashboard" and self.dashboard_service is not None:
            return DashboardPage(
                self.dashboard_service,
                self.currency_code,
                self.currency_symbol,
            )

        if name == "Transactions" and self.transaction_service is not None:
            page = TransactionsPage(
                self.transaction_service,
                self.currency_code,
                self.currency_symbol,
                worker_payment_service=self.worker_payment_service,
                liability_service=self.liability_service,
            )
            page.linked_payment_changed.connect(self._linked_payment_source_changed)
            return page

        if name == "Budget" and self.budget_service is not None:
            return BudgetPage(
                self.budget_service,
                self.currency_code,
                self.currency_symbol,
            )

        if name == "Liabilities" and self.liability_service is not None:
            page = LiabilitiesPage(
                self.liability_service,
                self.currency_code,
                self.currency_symbol,
            )
            page.open_count_changed.connect(self._set_liability_badge)
            page.linked_expenses_changed.connect(self._linked_expenses_changed)
            return page

        if name == "Workers" and self.worker_service is not None:
            return WorkersPage(
                self.worker_service,
                self.currency_code,
                self.currency_symbol,
                work_service=self.worker_work_service,
                payment_service=self.worker_payment_service,
                payroll_service=self.worker_payroll_service,
            )

        if name == "Reports" and self.report_service is not None:
            return ReportsPage(
                self.report_service,
                self.currency_code,
                self.currency_symbol,
            )

        if name == "Settings" and self.settings_service is not None:
            page = SettingsPage(
                self.settings_service,
                notification_service=self.notification_service,
                backup_service=self.backup_service,
                update_preferences_service=self.update_preferences_service,
                update_check_runner=self.update_check_runner,
            )
            page.theme_requested.connect(self.select_theme)
            page.worker_transaction_setting_changed.connect(
                self._worker_transaction_setting_changed
            )
            page.liability_transaction_setting_changed.connect(
                self._linked_expenses_changed
            )
            if self.notification_controller is not None:
                page.notification_settings_changed.connect(
                    self.notification_controller.reschedule
                )
                page.notification_test_requested.connect(
                    self.notification_controller.show_test
                )
            if getattr(page, "backup_card", None) is not None:
                page.backup_card.restore_completed.connect(QApplication.quit)
            return page

        if name == "Settings" and self.notification_service is not None:
            # Compatibility path retained for older Step 17 tests/helpers.
            page = NotificationsPage(
                self.notification_service,
                backup_service=self.backup_service,
            )
            if self.notification_controller is not None:
                page.settings_changed.connect(
                    self.notification_controller.reschedule
                )
                page.test_requested.connect(
                    self.notification_controller.show_test
                )
            if getattr(page, "backup_card", None) is not None:
                page.backup_card.restore_completed.connect(QApplication.quit)
            return page

        return create_placeholder_page(name)

    def _wire_worker_page(self, worker_page: WorkersPage) -> None:
        """Wire the single Workers page to finance views that mirror worker payments."""
        self.worker_subtabs.hide()
        worker_page.linked_expenses_changed.connect(self._worker_transaction_setting_changed)

    def _load_lazy_page(self, name: str) -> None:
        """Build a deferred page on first use and install it into its own scroll area."""
        if name not in self._lazy_unloaded_pages:
            return

        page = self._create_page(name)
        page.setMinimumSize(0, 0)
        page.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        page.setMinimumHeight(PAGE_SCROLL_MIN_HEIGHTS.get(name, 620))

        scroll = self.page_scrolls[name]
        previous = scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        scroll.setWidget(page)

        self.page_widgets[name] = page
        self._lazy_unloaded_pages.remove(name)
        self._freshly_built_pages.add(name)

        if isinstance(page, WorkersPage):
            self._wire_worker_page(page)

        # Step 23 was installed before deferred pages existed. Re-run the same
        # visual-only pass once so newly created buttons/cards get responsive
        # sizing immediately. Settings remains excluded inside Step 23 polish.
        QTimer.singleShot(0, lambda: apply_step23_polish(self))

    def _secure_update_check_succeeded(self, outcome) -> None:
        """Present only verified update decisions from the shared runner."""

        decision = getattr(outcome, "decision", None)
        if decision is None:
            return
        self.update_notification_banner.present(decision)

    def _connect_system_theme_updates(self) -> None:
        """Follow live Windows Light/Dark changes while System mode is selected."""
        app = QApplication.instance()
        if app is None:
            return
        hints = app.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None)
        if signal is None:
            return
        signal.connect(self._on_system_color_scheme_changed)
        self._system_style_hints = hints

    def _on_system_color_scheme_changed(self, *_args) -> None:
        """Refresh QSS after Qt has accepted the new operating-system scheme."""
        if getattr(self, "theme_name", None) != "system":
            return
        # Queue the refresh so the platform palette/style hints have completed
        # their own update before resolve_theme("system") is evaluated again.
        QTimer.singleShot(0, self._refresh_system_theme)

    def _refresh_system_theme(self) -> None:
        if getattr(self, "theme_name", None) != "system":
            return
        # Rebuilding the stylesheet is required: stylesheet("system") resolves
        # to concrete Light/Dark colors at call time. The background artwork
        # also resolves the current system scheme during repaint.
        self.apply_theme("system")

    def closeEvent(self, event) -> None:
        hints = getattr(self, "_system_style_hints", None)
        if hints is not None:
            try:
                hints.colorSchemeChanged.disconnect(self._on_system_color_scheme_changed)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)

    def _set_safe_initial_size(self) -> None:
        """Start slightly shorter while staying inside the usable desktop area."""
        screen = self.screen()
        if screen is None:
            self.resize(1120, 650)
            return
        available = screen.availableGeometry()
        width = min(1180, max(900, int(available.width() * 0.86)))
        # Page-level scrollbars now protect dense content, so the shell no
        # longer needs a tall startup geometry. Keep enough height for a
        # comfortable first view while allowing substantially more manual
        # vertical resizing than before.
        height = min(680, max(520, int(available.height() * 0.78)))
        self.resize(width, height)

    @property
    def current_page_name(self) -> str:
        current = self.pages.currentWidget()
        for name, container in self.page_containers.items():
            if container is current:
                return name
        return ""

    def _linked_expenses_changed(self, _enabled: bool | None = None) -> None:
        """Refresh built finance views after linked expense records change."""
        for name in ("Transactions", "Dashboard", "Reports"):
            if name in self._lazy_unloaded_pages:
                continue
            page = self.page_widgets.get(name)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()

    def _worker_transaction_setting_changed(self, _enabled: bool | None = None) -> None:
        """Compatibility alias retained for older tests/helpers."""
        self._linked_expenses_changed(_enabled)

    def _linked_payment_source_changed(self, source: str) -> None:
        """Refresh native payment views after deletion/undo from Transactions."""
        source_page = "Workers" if source == "worker_payment" else (
            "Liabilities" if source == "liability_payment" else None
        )
        if source == "liability_payment" and self.liability_service is not None:
            # A payment deletion can change Paid -> Open even when Liabilities
            # has not been lazily opened yet, so keep the sidebar badge current.
            self._set_liability_badge(self.liability_service.totals().open_count)
        names = ["Dashboard", "Reports"]
        if source_page is not None:
            names.append(source_page)
        for name in names:
            if name in self._lazy_unloaded_pages:
                continue
            page = self.page_widgets.get(name)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()

    def _set_liability_badge(self, count: int) -> None:
        nav = self.nav_buttons.get("Liabilities")
        if isinstance(nav, NavButton):
            nav.set_badge_count(count)

    def _reset_content_scroll(self) -> None:
        """Reset only the current page when that page owns an outer scroll area."""
        scroll = self.page_scrolls.get(self.current_page_name)
        if scroll is None:
            return
        scroll.verticalScrollBar().setValue(0)
        scroll.horizontalScrollBar().setValue(0)

    def _sync_worker_subtab(self, index: int = 0) -> None:
        """Compatibility no-op: Workers is a single page."""
        self.worker_subtabs.hide()

    def _worker_child_tab_changed(self, index: int = 0) -> None:
        """Compatibility no-op: Workers is a single page."""
        self.worker_subtabs.hide()

    def navigate(self, name: str) -> None:
        if name not in self.page_widgets:
            raise ValueError("Unknown navigation page")

        if name in self._lazy_unloaded_pages:
            self._load_lazy_page(name)
        freshly_built = name in self._freshly_built_pages

        container = self.page_containers[name]
        self.pages.setCurrentWidget(container)
        self.content_scroll = self.page_scrolls[name]

        # Every navigation starts the destination page from the top-left.
        # Reset immediately, then once more after refresh/layout work settles so
        # a page can never reopen at an old scroll position.
        destination_scroll = self.page_scrolls[name]
        destination_scroll.verticalScrollBar().setValue(0)
        destination_scroll.horizontalScrollBar().setValue(0)

        self.page_title.setText(name)
        self.nav_buttons[name].setChecked(True)

        # Workers is a single-page workspace; no child navigation is shown.
        self.worker_subtabs.hide()

        if name == "Dashboard" and self.dashboard_service is not None:
            dashboard = self.page_widgets[name]
            if not freshly_built and hasattr(dashboard, "refresh"):
                dashboard.refresh()
            self.feedback.setText("Dashboard refreshed from your saved transaction records.")
        elif name == "Transactions" and self.transaction_service is not None:
            transactions = self.page_widgets[name]
            if not freshly_built and hasattr(transactions, "refresh"):
                transactions.refresh()
            self.feedback.setText("Transactions opened. Income, expenses, categories, delete, and undo are active.")
        elif name == "Budget" and self.budget_service is not None:
            budget = self.page_widgets[name]
            if not freshly_built and hasattr(budget, "refresh"):
                budget.refresh()
            self.feedback.setText("Budget opened. Monthly, category, spending progress, and carry-forward are active.")
        elif name == "Liabilities" and self.liability_service is not None:
            liabilities = self.page_widgets[name]
            if not freshly_built and hasattr(liabilities, "refresh"):
                liabilities.refresh()
            self.feedback.setText("Liabilities opened. Loans, payments, and remaining balances are active.")
        elif name == "Workers" and self.worker_service is not None:
            workers = self.page_widgets[name]
            if not freshly_built and hasattr(workers, "refresh"):
                workers.refresh()
            self.feedback.setText("Workers opened. Profiles, work records, payments, and advances are active.")
        elif name == "Reports" and self.report_service is not None:
            reports = self.page_widgets[name]
            if not freshly_built and hasattr(reports, "refresh"):
                reports.refresh()
            self.feedback.setText("Reports opened. Monthly totals, category spending, and six-month trend are active.")
        elif name == "Settings" and self.settings_service is not None:
            settings_page = self.page_widgets[name]
            if not freshly_built and hasattr(settings_page, "refresh"):
                settings_page.refresh()
            self.feedback.setText(
                "Settings opened. Currency, appearance, security, notifications, "
                "data backup, and application information are connected."
            )
        elif name == "Settings" and self.notification_service is not None:
            notifications = self.page_widgets[name]
            if not freshly_built and hasattr(notifications, "refresh"):
                notifications.refresh()
            self.feedback.setText(
                "Settings opened. Daily local desktop reminders are active."
            )
        else:
            self.feedback.setText(f"{name} opened. This module is still a placeholder.")

        self._freshly_built_pages.discard(name)

        # Refresh/layout work can change the scrollbar range after navigation.
        # Queue a second reset so the visible page reliably lands at the top.
        QTimer.singleShot(
            0,
            lambda scroll=destination_scroll: (
                scroll.verticalScrollBar().setValue(0),
                scroll.horizontalScrollBar().setValue(0),
            ),
        )
        QTimer.singleShot(0, self._update_responsive_buttons)

        # A newly shown page can receive its final card width only after the
        # stacked widget switches. Refresh cached Step 23 summary cards once on
        # the next event-loop turn; this is lightweight and avoids a full-tree
        # style pass on navigation.
        controller = getattr(self, "_step23_controller", None)
        if controller is not None and hasattr(controller, "refresh_summaries"):
            QTimer.singleShot(0, controller.refresh_summaries)

    def closeEvent(self, event) -> None:
        if self.notification_controller is not None:
            self.notification_controller.stop()
        super().closeEvent(event)

    def toggle_sidebar(self) -> None:
        self.sidebar_collapsed = not self.sidebar_collapsed
        if self.sidebar_collapsed:
            self.sidebar.setFixedWidth(self.COLLAPSED_SIDEBAR_WIDTH)
            self.logo_plate.hide()
            self.brand_text.hide()
            self.privacy_label.hide()
            self.sidebar_note.hide()
            self.brand_row_widget.layout().setAlignment(
                self.collapse_button, Qt.AlignmentFlag.AlignHCenter
            )
            self.collapse_button.setToolTip("Expand sidebar")
            self.collapse_button.setAccessibleName("Expand sidebar")
            self.collapse_button.setFixedSize(36, 36)
            self.collapse_button.setIconSize(QSize(22, 22))
            for nav in self.nav_buttons.values():
                nav.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                if isinstance(nav, NavButton):
                    nav._position_badge()
            self.lock_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            self.lock_button.setFixedWidth(40)
            self.lock_button.setToolTip(
                "Lock ChitLog and require your PIN or password to continue."
            )
        else:
            self.sidebar.setFixedWidth(self.EXPANDED_SIDEBAR_WIDTH)
            self.logo_plate.show()
            self.brand_text.show()
            self.privacy_label.setVisible(self.height() >= 500)
            self.sidebar_note.setVisible(self.height() >= 560)
            self.collapse_button.setToolTip("Collapse sidebar")
            self.collapse_button.setAccessibleName("Collapse sidebar")
            self.collapse_button.setFixedSize(44, 44)
            self.collapse_button.setIconSize(QSize(24, 24))
            for nav in self.nav_buttons.values():
                nav.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                if isinstance(nav, NavButton):
                    nav._position_badge()
            self.lock_button.setMaximumWidth(16777215)
            self.lock_button.setMinimumWidth(0)
            self.lock_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
        self.sidebar.updateGeometry()

    def resizeEvent(self, event) -> None:
        """Keep horizontal and vertical density usable while resizing."""
        super().resizeEvent(event)
        self._update_vertical_density()
        QTimer.singleShot(0, self._update_responsive_buttons)

    def _update_vertical_density(self) -> None:
        """Let the shell shrink vertically without sidebar controls colliding."""
        short = self.height() < 560
        very_short = self.height() < 500

        nav_height = 36 if short else 40
        for nav in self.nav_buttons.values():
            nav.setMinimumHeight(nav_height)
            nav.setMaximumHeight(nav_height if short else 16777215)
        self.lock_button.setMinimumHeight(nav_height)
        self.lock_button.setMaximumHeight(nav_height if short else 16777215)

        # These labels are helpful but non-essential; hiding them on a very
        # short window frees vertical room for navigation instead of forcing
        # the entire application to stay tall.
        self.sidebar_note.setVisible(not short and not self.sidebar_collapsed)
        self.privacy_label.setVisible(not very_short and not self.sidebar_collapsed)

    def _update_responsive_buttons(self) -> None:
        current = self.pages.currentWidget()
        if isinstance(current, QScrollArea):
            width = current.viewport().width()
        elif current is not None:
            width = current.width()
        else:
            width = self.main_panel.width()
        compact = width < 900

        self.worker_subtabs.hide()

        if getattr(self, "_buttons_compact", None) == compact:
            return
        self._buttons_compact = compact

        # Navigation buttons have their own icon/text responsive behavior and
        # must not be shrunk by the generic button density rule. Filter controls
        # already have a dedicated compact style that remains authoritative.
        widgets = list(self.findChildren(QPushButton)) + list(self.findChildren(QToolButton))
        for widget in widgets:
            if widget.property("role") == "nav":
                continue
            widget.setProperty("responsiveCompact", compact)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.updateGeometry()

    def apply_theme(self, name: str) -> None:
        if name not in APPEARANCE_THEMES:
            raise ValueError("Unsupported theme")
        self.theme_name = name
        self.setStyleSheet(stylesheet(name))
        # Worker activity rows use subtle palette-derived item brushes in addition
        # to QSS. Rebuild that page after a theme change so Work/Payment tints
        # always match the active Light/Dark/System palette.
        if "Workers" not in getattr(self, "_lazy_unloaded_pages", set()):
            worker_page = getattr(self, "page_widgets", {}).get("Workers")
            if isinstance(worker_page, WorkersPage):
                QTimer.singleShot(0, worker_page.refresh)
        for button_name, theme_button in self.theme_buttons.items():
            theme_button.setChecked(button_name == name)
        self.update()

        # setStyleSheet() replaces the Step 23 overlay. Restore and repolish
        # synchronously so every already-created summary card receives the new
        # effective Light/Dark/System theme before this click returns. A queued
        # layout refresh is still useful after Qt finishes recalculating sizes.
        if bool(self.property("step23PolishApplied")):
            apply_step23_polish(self)
            controller = getattr(self, "_step23_controller", None)
            if controller is not None:
                QTimer.singleShot(0, controller.schedule_summary_refresh)

    def select_theme(self, name: str) -> None:
        self.apply_theme(name)
        try:
            if self.settings:
                self.settings.save_theme(name)
            if self.theme_saver:
                self.theme_saver(name)
        except (OSError, RuntimeError):
            self.feedback.setText(
                "Theme changed for this session. ChitLog could not save the preference."
            )
            return
        effective = resolve_theme(name)
        shown = name.title() if name != "system" else f"System ({effective.title()})"
        self.feedback.setText(f"{shown} theme selected. Preference saved.")


def create_window(
    assets: Path = ASSETS,
    settings: AppearanceSettings | None = None,
    theme_saver=None,
    transaction_service=None,
    dashboard_service=None,
    budget_service=None,
    liability_service=None,
    report_service=None,
    notification_service=None,
    backup_service=None,
    settings_service=None,
    update_preferences_service=None,
    update_check_runner=None,
    lazy_pages: bool = False,
    worker_service=None,
    currency_code: str = "LKR",
    currency_symbol: str = "Rs",
    worker_work_service=None,
    worker_payment_service=None,
    worker_payroll_service=None,
) -> MainWindow:
    return MainWindow(
        assets=assets,
        settings=settings,
        theme_saver=theme_saver,
        transaction_service=transaction_service,
        dashboard_service=dashboard_service,
        budget_service=budget_service,
        liability_service=liability_service,
        report_service=report_service,
        notification_service=notification_service,
        backup_service=backup_service,
        settings_service=settings_service,
        update_preferences_service=update_preferences_service,
        update_check_runner=update_check_runner,
        lazy_pages=lazy_pages,
        worker_service=worker_service,
        currency_code=currency_code,
        currency_symbol=currency_symbol,
        worker_work_service=worker_work_service,
        worker_payment_service=worker_payment_service,
        worker_payroll_service=worker_payroll_service,
    )
