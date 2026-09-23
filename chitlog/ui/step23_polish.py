"""Step 23 UI/UX polish helpers.

Clean baseline based on the Dashboard Responsive Card Fix.

Presentation only. This module intentionally DOES NOT move, reparent, reorder,
or otherwise change the location of any button or control.

Included:
- responsive summary-card sizing with conservative maximum bounds,
- restrained theme-aware semantic summary-card accents,
- compact fixed-footprint button sizing outside Settings,
- compact Refresh/Filter/Search and month-navigation buttons,
- idempotent button sizing and debounced summary-card resize updates,
- cached summary-card discovery so normal interaction stays responsive.

Excluded on purpose:
- all action-row relocation/reflow logic from later Step 23 experiments,
- all business/database/security/payroll changes.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QWidget,
)

# Compact action footprint. + Liability is the visual reference: short actions
# stay at the same compact 96 px footprint, while longer labels may use only the
# extra width they actually need, capped at 140 px. Every action gets a fixed
# post-layout width/height so layouts cannot stretch buttons into large blocks.
ACTION_HEIGHT = 36
ACTION_MIN_WIDTH = 96
ACTION_MID_WIDTH = 128
ACTION_MAX_WIDTH = 164
ACTION_TEXT_PADDING = 32

# Small utility controls remain intentionally smaller than primary actions and
# also receive fixed footprints.
COMPACT_HEIGHT = 30
COMPACT_WIDTH = 88
NAV_ARROW_WIDTH = 40

SEARCH_HEIGHT = 32
SEARCH_MAX_WIDTH = 300

# Summary cards stay compact. Existing page-specific caps are respected; these
# values are only global ceilings/fallbacks for cards that did not define one.
# This prevents the Step 23 overlay from making small cards larger than their
# page intended while still leaving enough room for wrapped helper text.
SUMMARY_MIN_HEIGHT = 104
SUMMARY_MAX_HEIGHT = 128
SUMMARY_DENSE_MAX_HEIGHT = 136
SUMMARY_MIN_WIDTH = 150
SUMMARY_MAX_WIDTH = 560
SUMMARY_COMPACT_WIDTH = 380
SUMMARY_TIGHT_WIDTH = 300
UNBOUNDED_WIDGET_SIZE = 16777215

_COMPACT_BUTTON_WORDS = {
    "refresh",
    "search",
    "filter",
    "apply filter",
    "clear filter",
    "clear filters",
    "reset filter",
    "reset filters",
}

_NAV_LABELS = {
    "dashboard",
    "transactions",
    "budget",
    "liabilities",
    "workers",
    "reports",
    "settings",
}

_SUMMARY_HINTS = (
    "current balance",
    "total balance",
    "this month income",
    "total income",
    "this month expenses",
    "total expenses",
    "this month remaining",
    "this month net",
    "monthly net",
    "net remaining",
    "budget status",
    "outstanding worker",
    "total liabilities",
    "outstanding liabilities",
    "outstanding balance",
    "total borrowed",
    "total paid",
    "remaining due",
    "amount to pay",
    "workers with balance",
    "earnings",
    "payments",
    "advances",
)


def _norm(value: str) -> str:
    return " ".join(str(value or "").replace("&", "").split()).strip().lower()


def _settings_page(root: QWidget) -> QWidget | None:
    pages = getattr(root, "page_widgets", None)
    if isinstance(pages, dict):
        page = pages.get("Settings")
        if isinstance(page, QWidget):
            return page
    return None


def _is_in_settings(root: QWidget, widget: QWidget) -> bool:
    settings = _settings_page(root)
    if settings is None:
        return False
    return widget is settings or settings.isAncestorOf(widget)


def _is_navigation_button(button: QPushButton) -> bool:
    text = _norm(button.text())
    role = _norm(button.property("role"))
    name = _norm(button.objectName())
    return (
        text in _NAV_LABELS
        or "nav" in role
        or "sidebar" in role
        or "nav" in name
        or "sidebar" in name
    )


def _is_compact_button(button: QPushButton) -> bool:
    text = _norm(button.text())
    if text in _COMPACT_BUTTON_WORDS:
        return True
    return text.startswith("refresh ") or text.startswith("filter ")


def _is_month_arrow(button: QPushButton) -> bool:
    return _norm(button.text()) in {"<", ">", "‹", "›", "previous", "next"}


def _polish_button(root: QWidget, button: QPushButton) -> None:
    """Apply compact sizing only when this button's visual state changed.

    Step 23 originally unpolished/repolished every button after every click and
    window resize. On a real Qt widget tree that is expensive and made the UI
    feel sluggish. The signature below makes this operation idempotent: existing
    buttons are effectively free on later passes unless their text/size tier
    actually changed.
    """
    # User requested Settings to remain untouched for now. Sidebar navigation is
    # also excluded so the existing navigation geometry is preserved.
    if _is_in_settings(root, button) or _is_navigation_button(button):
        return
    normalized_text = _norm(button.text())
    if not normalized_text:
        return

    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    density = "action"
    font_tier = "normal"
    target_width = ACTION_MIN_WIDTH
    target_height = ACTION_HEIGHT

    if _is_month_arrow(button):
        density = "compactNav"
        target_width = NAV_ARROW_WIDTH
        target_height = COMPACT_HEIGHT
    elif _is_compact_button(button):
        density = "compact"
        target_width = COMPACT_WIDTH
        target_height = COMPACT_HEIGHT
    else:
        text = button.text().replace("&", "")
        tiers = (
            ("normal", 10.0, ACTION_TEXT_PADDING),
            ("small", 9.0, ACTION_TEXT_PADDING - 4),
            ("tiny", 8.0, ACTION_TEXT_PADDING - 8),
        )
        widths = (ACTION_MIN_WIDTH, ACTION_MID_WIDTH, ACTION_MAX_WIDTH)
        target_width = ACTION_MAX_WIDTH
        font_tier = "tiny"

        for tier_name, point_size, padding in tiers:
            reference_font = button.font()
            reference_font.setPointSizeF(point_size)
            needed_width = QFontMetrics(reference_font).horizontalAdvance(text) + padding
            fitting_width = next((width for width in widths if needed_width <= width), None)
            if fitting_width is not None:
                target_width = fitting_width
                font_tier = tier_name
                break

    signature = f"{normalized_text}|{density}|{font_tier}|{target_width}|{target_height}"
    if button.property("step23ButtonSignature") == signature:
        return

    button.setProperty("step23Density", density)
    button.setProperty("step23FontTier", font_tier)
    button.setProperty("step23ButtonSignature", signature)
    button.setFixedSize(target_width, target_height)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # Dynamic-property selectors need a repolish only when their signature
    # changes. Avoiding unconditional repolish is the main performance fix.
    style = button.style()
    if style is not None:
        style.unpolish(button)
        style.polish(button)
    button.updateGeometry()

    if not button.accessibleName():
        button.setAccessibleName(button.text().replace("&", ""))
    if not button.toolTip() and len(button.text()) <= 56:
        button.setToolTip(button.text().replace("&", ""))

def _polish_all_buttons(root: QWidget) -> None:
    for button in root.findChildren(QPushButton):
        _polish_button(root, button)


def _polish_search(root: QWidget, field: QLineEdit) -> None:
    if _is_in_settings(root, field):
        return
    hint = " ".join(
        part for part in (
            field.objectName(),
            field.accessibleName(),
            field.placeholderText(),
        ) if part
    )
    if "search" not in _norm(hint):
        return
    field.setFixedHeight(SEARCH_HEIGHT)
    field.setMaximumWidth(SEARCH_MAX_WIDTH)
    field.setClearButtonEnabled(True)
    field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if not field.accessibleName():
        field.setAccessibleName(field.placeholderText() or "Search")


def _looks_like_filter(widget: QWidget) -> bool:
    hint = " ".join(
        part for part in (
            widget.objectName(),
            widget.accessibleName(),
            widget.toolTip(),
        ) if part
    )
    hint = _norm(hint)
    return any(word in hint for word in ("filter", "status", "type", "kind", "category", "date range"))


def _polish_filter(root: QWidget, widget: QWidget) -> None:
    if _is_in_settings(root, widget) or not _looks_like_filter(widget):
        return
    widget.setFixedHeight(SEARCH_HEIGHT)
    if isinstance(widget, QComboBox):
        widget.setMaximumWidth(220)
    elif isinstance(widget, QDateEdit):
        widget.setMaximumWidth(170)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


def _summary_labels(frame: QFrame) -> list[QLabel]:
    # Card title/value/helper labels are direct children of Card. Restricting
    # the scan to direct labels prevents nested tables/forms from being treated
    # as part of a summary card.
    return [
        label
        for label in frame.findChildren(QLabel)
        if label.parentWidget() is frame and _norm(label.text())
    ]


def _summary_text(frame: QFrame) -> str:
    return " | ".join(_norm(label.text()) for label in _summary_labels(frame))


def _is_summary_frame(frame: QFrame) -> bool:
    # QLabel inherits QFrame in Qt. The old detector therefore classified every
    # QLabel with role="metric" as a *summary frame*, gave the label a 104-132
    # px card height, and applied card borders/backgrounds to it. That produced
    # the inner highlighted rectangle and overlapping helper text visible in the
    # Dashboard screenshot. A real summary card must instead CONTAIN a direct
    # metric label.
    if isinstance(frame, QLabel):
        return False
    if frame.findChildren(QAbstractItemView):
        return False

    labels = _summary_labels(frame)
    return any(_norm(label.property("role")) == "metric" for label in labels)


def _summary_accent(frame: QFrame) -> str:
    text = _summary_text(frame)

    # Most-specific matches first so the main Dashboard four get distinct,
    # predictable accents.
    if "current balance" in text or "total balance" in text:
        return "balance"
    if "income" in text or "earnings" in text:
        return "income"
    if "expense" in text or "advances" in text:
        return "expense"
    if "net" in text or "remaining" in text:
        return "net"
    if "budget" in text:
        return "budget"
    if "liabilit" in text or "borrowed" in text or "amount to pay" in text or "remaining due" in text:
        return "liability"
    if "worker" in text:
        return "worker"
    if "paid" in text or "payments" in text:
        return "paid"
    return "general"


def _polish_summary(frame: QFrame) -> None:
    """Keep one summary card compact without repeatedly restyling it."""
    if not _is_summary_frame(frame):
        return

    # Preserve page-authored bounds without freezing the first responsive state.
    # Transactions/Payroll legitimately tighten their own card heights when the
    # page gets narrow. If a bound differs from the last value Step 23 applied,
    # treat it as a new page-authored limit and use that on the next pass.
    current_limits = {
        "min_width": frame.minimumWidth(),
        "max_width": frame.maximumWidth(),
        "min_height": frame.minimumHeight(),
        "max_height": frame.maximumHeight(),
    }
    for key, current in current_limits.items():
        original_attr = f"_step23_original_{key}"
        applied_attr = f"_step23_applied_{key}"
        if not hasattr(frame, original_attr):
            setattr(frame, original_attr, current)
            continue
        last_applied = getattr(frame, applied_attr, None)
        if last_applied is not None and int(current) != int(last_applied):
            setattr(frame, original_attr, current)

    original_max_width = int(frame._step23_original_max_width)
    target_max_width = SUMMARY_MAX_WIDTH
    if original_max_width < UNBOUNDED_WIDGET_SIZE:
        target_max_width = min(target_max_width, original_max_width)
    target_min_width = min(
        max(int(frame._step23_original_min_width), SUMMARY_MIN_WIDTH),
        target_max_width,
    )

    labels = _summary_labels(frame)
    global_height_cap = SUMMARY_DENSE_MAX_HEIGHT if len(labels) >= 4 else SUMMARY_MAX_HEIGHT
    original_max_height = int(frame._step23_original_max_height)
    target_max_height = global_height_cap
    if original_max_height < UNBOUNDED_WIDGET_SIZE:
        target_max_height = min(target_max_height, original_max_height)
    target_min_height = min(
        max(int(frame._step23_original_min_height), SUMMARY_MIN_HEIGHT),
        target_max_height,
    )

    # Font density follows the actual card width, not the whole page width.
    card_width = frame.width()
    if card_width <= 0:
        card_width = frame.sizeHint().width()
    if card_width < SUMMARY_TIGHT_WIDTH:
        density = "tight"
        margins, spacing, metric_height = 8, 3, 24
    elif card_width < SUMMARY_COMPACT_WIDTH:
        density = "compact"
        margins, spacing, metric_height = 9, 3, 27
    else:
        density = "normal"
        margins, spacing, metric_height = 10, 4, 30

    accent = _summary_accent(frame)
    signature = (
        f"{density}|{accent}|{target_min_width}|{target_max_width}|"
        f"{target_min_height}|{target_max_height}|{metric_height}|{len(labels)}"
    )
    if frame.property("step23SummarySignature") == signature:
        return

    frame.setProperty("step23Summary", True)
    frame.setProperty("step23Accent", accent)
    frame.setProperty("step23SummaryDensity", density)
    frame.setProperty("step23SummarySignature", signature)

    frame.setMinimumWidth(target_min_width)
    frame.setMaximumWidth(target_max_width)
    frame.setMinimumHeight(target_min_height)
    frame.setMaximumHeight(target_max_height)
    frame._step23_applied_min_width = target_min_width
    frame._step23_applied_max_width = target_max_width
    frame._step23_applied_min_height = target_min_height
    frame._step23_applied_max_height = target_max_height
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    layout = frame.layout()
    if layout is not None:
        layout.setContentsMargins(margins, margins, margins, margins)
        layout.setSpacing(spacing)

    for label in labels:
        role = _norm(label.property("role"))
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if role == "metric":
            label.setWordWrap(False)
            label.setMinimumHeight(metric_height)
            label.setMaximumHeight(metric_height + 6)
        elif role == "muted":
            label.setMinimumHeight(0)
            label.setMaximumHeight(UNBOUNDED_WIDGET_SIZE)
            label.setWordWrap(True)
        else:
            label.setMinimumHeight(0)
            label.setMaximumHeight(UNBOUNDED_WIDGET_SIZE)

    # Only cards whose density/accent/geometry signature changed are repolished.
    style = frame.style()
    if style is not None:
        style.unpolish(frame)
        style.polish(frame)
    for label in labels:
        style = label.style()
        if style is not None:
            style.unpolish(label)
            style.polish(label)
        label.updateGeometry()

def _set_theme_property(root: QWidget) -> None:
    """Update the Step 23 theme selector only when it actually changes."""
    palette = root.palette()
    bg = palette.color(QPalette.ColorRole.Window)
    luminance = (0.2126 * bg.red()) + (0.7152 * bg.green()) + (0.0722 * bg.blue())
    theme_value = "dark" if luminance < 128 else "light"
    if root.property("step23Theme") == theme_value:
        return

    root.setProperty("step23Theme", theme_value)
    style = root.style()
    if style is not None:
        style.unpolish(root)
        style.polish(root)
    root.update()


def _discover_summary_frames(root: QWidget) -> list[QFrame]:
    """Find summary cards only on explicit Step 23 passes, never every resize."""
    cards: list[QFrame] = []
    for frame in root.findChildren(QFrame):
        # QLabel is a QFrame subclass; never apply card geometry to labels.
        if isinstance(frame, QLabel):
            continue
        if _is_summary_frame(frame):
            cards.append(frame)
    root._step23_summary_frames = cards
    return cards


def _cached_summary_frames(root: QWidget) -> list[QFrame]:
    cards = getattr(root, "_step23_summary_frames", None)
    if not isinstance(cards, list):
        return _discover_summary_frames(root)
    return cards


def _polish_summaries(root: QWidget, *, discover: bool = False) -> None:
    cards = _discover_summary_frames(root) if discover else _cached_summary_frames(root)
    for frame in cards:
        try:
            _polish_summary(frame)
        except RuntimeError:
            # A deferred page placeholder may have been deleted. The next
            # explicit apply will rebuild the cache from live widgets.
            continue


def _ensure_overlay_stylesheet(root: QWidget) -> None:
    """Restore the Step 23 overlay after a Light/Dark/System theme switch."""
    overlay = root.property("step23OverlayCss")
    if not isinstance(overlay, str) or not overlay:
        return
    if "CHITLOG_STEP23_OVERLAY" in root.styleSheet():
        return
    root.setStyleSheet(root.styleSheet() + overlay)


def _apply_visual_state(root: QWidget, *, discover_summaries: bool = False) -> None:
    # IMPORTANT: no layout/reparent/reorder calls live in this path.
    _ensure_overlay_stylesheet(root)
    _set_theme_property(root)
    _polish_all_buttons(root)
    _polish_summaries(root, discover=discover_summaries)


class _Step23Controller(QObject):
    """Debounced polish refresh plus consistent click-away table selection."""

    RESIZE_DEBOUNCE_MS = 90

    def __init__(self, root: QWidget):
        super().__init__(root)
        self.root = root
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(self.RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self.refresh_summaries)
        self._table_views: list[QTableWidget] = []
        root.installEventFilter(self)

        # Child widgets receive their own mouse events, so install this very
        # lightweight filter on the application as well. The filter immediately
        # ignores events outside this ChitLog window and non-mouse-release events.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def schedule_summary_refresh(self) -> None:
        # Restarting a single timer coalesces dozens of native Windows resize
        # events into one cheap summary-card density update after motion settles.
        self._resize_timer.start()

    def refresh_summaries(self) -> None:
        _polish_summaries(self.root, discover=False)

    def refresh_tables(self) -> None:
        """Cache live selectable record tables, including lazily-built pages."""
        self._table_views = [
            table
            for table in self.root.findChildren(QTableWidget)
            if table.selectionMode() != QAbstractItemView.SelectionMode.NoSelection
        ]

    @staticmethod
    def _inside_table(widget: QWidget) -> bool:
        """Return True when the click target belongs to a table or its chrome."""
        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, QTableWidget):
                return True
            current = current.parentWidget()
        return False

    def clear_table_selections(self) -> None:
        """Clear both selected rows and the stale current index on every table."""
        for table in tuple(self._table_views):
            try:
                model = table.selectionModel()
                if model is None:
                    continue
                if model.hasSelection() or model.currentIndex().isValid():
                    # QItemSelectionModel.clear() resets BOTH selection and the
                    # current index. QTableWidget.clearSelection() alone leaves
                    # currentRow() pointing at the previous row, which caused a
                    # restored liability to make the following row look selected.
                    model.clear()
            except RuntimeError:
                # A lazy-page placeholder/table may have been deleted between
                # explicit Step 23 refreshes. It will disappear on the next scan.
                continue

    def refresh_all(self) -> None:
        # Explicit use only: initial setup, lazy-page creation, or a theme change.
        _apply_visual_state(self.root, discover_summaries=True)
        self.refresh_tables()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        event_type = event.type()
        if watched is self.root and event_type == QEvent.Type.Resize:
            self.schedule_summary_refresh()
            return False

        if event_type != QEvent.Type.MouseButtonRelease or not isinstance(watched, QWidget):
            return False
        if watched is not self.root and not self.root.isAncestorOf(watched):
            return False
        if self._inside_table(watched):
            return False

        # Queue the clear until after the clicked widget has handled this mouse
        # release. Action buttons can therefore still read the selected record
        # before the normal click-away behavior resets the table selection.
        QTimer.singleShot(0, self.clear_table_selections)
        return False

def apply_step23_polish(root: QWidget) -> None:
    """Apply Step 23 visual polish without changing any button locations."""
    if not root.property("step23PolishApplied"):
        root.setProperty("step23PolishApplied", True)

        # Add one stylesheet overlay only. It changes appearance/sizing state,
        # never layout position.
        overlay_css = r"""
            /* CHITLOG_STEP23_OVERLAY */
            QPushButton[step23Density="action"] { font-size: 10pt; padding: 5px 9px; }
            QPushButton[step23Density="action"][step23FontTier="small"] { font-size: 9pt; padding-left: 7px; padding-right: 7px; }
            QPushButton[step23Density="action"][step23FontTier="tiny"] { font-size: 8pt; padding-left: 6px; padding-right: 6px; }
            QPushButton[step23Density="compact"] { font-size: 9pt; padding: 3px 7px; }
            QPushButton[step23Density="compactNav"] { font-size: 9pt; padding: 2px 6px; }
            QFrame[step23Summary="true"] { padding: 0px; border-radius: 12px; }

            /* Summary typography scales with the card itself so DPI scaling or
               a narrow content pane cannot make value/helper text collide. */
            QFrame[step23Summary="true"][step23SummaryDensity="normal"] QLabel[role="heading"] { font-size: 12pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="normal"] QLabel[role="metric"] { font-size: 20pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="normal"] QLabel[role="muted"] { font-size: 9.5pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="compact"] QLabel[role="heading"] { font-size: 11pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="compact"] QLabel[role="metric"] { font-size: 18pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="compact"] QLabel[role="muted"] { font-size: 9pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="tight"] QLabel[role="heading"] { font-size: 10pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="tight"] QLabel[role="metric"] { font-size: 16pt; }
            QFrame[step23Summary="true"][step23SummaryDensity="tight"] QLabel[role="muted"] { font-size: 8.5pt; }

            /* Step 23 highlight refresh: keep summary cards inside the ChitLog
               brand family instead of rainbow semantic fills. The body stays
               calm; a slim top accent plus a very light teal/navy wash gives
               hierarchy without looking like a nested card. */
            QWidget[step23Theme="light"] QFrame[step23Summary="true"] {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(255,255,255,238), stop:1 rgba(47,157,148,18));
                border: 1px solid #C4D3D5;
                border-top: 3px solid #2F9D94;
            }
            QWidget[step23Theme="light"] QFrame[step23Accent="balance"],
            QWidget[step23Theme="light"] QFrame[step23Accent="budget"],
            QWidget[step23Theme="light"] QFrame[step23Accent="worker"] { border-top-color: #2F9D94; }
            QWidget[step23Theme="light"] QFrame[step23Accent="income"],
            QWidget[step23Theme="light"] QFrame[step23Accent="paid"] { border-top-color: #025F67; }
            QWidget[step23Theme="light"] QFrame[step23Accent="expense"],
            QWidget[step23Theme="light"] QFrame[step23Accent="liability"] { border-top-color: #063154; }
            QWidget[step23Theme="light"] QFrame[step23Accent="net"],
            QWidget[step23Theme="light"] QFrame[step23Accent="general"] { border-top-color: #4D8F94; }
            QWidget[step23Theme="light"] QFrame[step23Summary="true"] QLabel[role="metric"] { color: #025F67; }

            QWidget[step23Theme="dark"] QFrame[step23Summary="true"] {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(11,48,71,232), stop:1 rgba(2,95,103,82));
                border: 1px solid #416071;
                border-top: 3px solid #7AD5CB;
            }
            QWidget[step23Theme="dark"] QFrame[step23Accent="income"],
            QWidget[step23Theme="dark"] QFrame[step23Accent="paid"] { border-top-color: #7AD5CB; }
            QWidget[step23Theme="dark"] QFrame[step23Accent="expense"],
            QWidget[step23Theme="dark"] QFrame[step23Accent="liability"] { border-top-color: #BCC5CC; }
            QWidget[step23Theme="dark"] QFrame[step23Accent="net"],
            QWidget[step23Theme="dark"] QFrame[step23Accent="general"] { border-top-color: #5AB8B0; }
            QWidget[step23Theme="dark"] QFrame[step23Summary="true"] QLabel[role="metric"] { color: #7AD5CB; }
            """
        root.setProperty("step23OverlayCss", overlay_css)
        root.setStyleSheet(root.styleSheet() + overlay_css)

        controller = _Step23Controller(root)
        root._step23_controller = controller

    # Explicit calls happen only at startup, after a lazy page is created, or
    # after a theme stylesheet replacement. Re-scan at those moments so new
    # widgets are registered, but rely on idempotent signatures so existing
    # controls are not repolished.
    for field in root.findChildren(QLineEdit):
        _polish_search(root, field)
    for combo in root.findChildren(QComboBox):
        _polish_filter(root, combo)
    for date_field in root.findChildren(QDateEdit):
        _polish_filter(root, date_field)

    _apply_visual_state(root, discover_summaries=True)

    controller = getattr(root, "_step23_controller", None)
    if controller is not None and hasattr(controller, "refresh_tables"):
        controller.refresh_tables()

    # One cheap queued card-density pass is enough after Qt settles layout. The
    # previous 0/120/350 ms full-tree passes were a major source of startup and
    # navigation lag.
    controller = getattr(root, "_step23_controller", None)
    if isinstance(controller, _Step23Controller):
        QTimer.singleShot(0, controller.refresh_summaries)
