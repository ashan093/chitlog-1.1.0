"""Central ChitLog palette, typography, spacing, and widget states."""
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette

from chitlog.core.config import ASSETS

SCOOTER = "#2F9D94"
ALABASTER = "#F7F6F2"
HEATHER = "#BCC5CC"
BLUE_LAGOON = "#025F67"
SAPPHIRE = "#063154"
ERROR_LIGHT = "#B83C4A"
ERROR_DARK = "#FF9A93"

SPACE = {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32}
FONT_FAMILY = "Segoe UI"


@dataclass(frozen=True)
class Theme:
    background: str
    surface: str
    glass: str
    text: str
    muted: str
    border: str
    field: str
    selected: str
    accent_text: str
    error: str


THEMES = {
    "light": Theme(
        ALABASTER,
        "#FFFFFF",
        "rgba(255,255,255,205)",
        SAPPHIRE,
        "#4B6475",
        "#C4D3D5",
        "#FFFFFF",
        "#E0F1EE",
        BLUE_LAGOON,
        ERROR_LIGHT,
    ),
    "dark": Theme(
        SAPPHIRE,
        "#0B3047",
        "rgba(11,48,71,210)",
        ALABASTER,
        HEATHER,
        "#416071",
        "#08273B",
        "#124C57",
        "#7AD5CB",
        ERROR_DARK,
    ),
}


def resolve_theme(name: str, app: QGuiApplication | None = None) -> str:
    if name in THEMES:
        return name

    app = app or QGuiApplication.instance()
    if app is None:
        return "light"

    try:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
        if scheme == Qt.ColorScheme.Light:
            return "light"
    except Exception:
        pass

    color = app.palette().color(QPalette.ColorRole.Window)
    return "dark" if color.lightness() < 128 else "light"


def stylesheet(name: str) -> str:
    """Return the application stylesheet.

    Font sizes use points rather than pixels. Besides scaling better on Windows,
    this prevents Qt from producing a pixel-sized QFont whose pointSize() is -1
    when native widgets later derive a font from it.

    Interactive controls keep the same border width in normal/focus states so
    focusing or clicking them cannot change layout size hints.
    """
    resolved_name = resolve_theme(name)
    t = THEMES[resolved_name]
    checkmark_path = (ASSETS / "checkbox_check.png").resolve().as_posix()
    payroll_checkbox_border = ALABASTER if resolved_name == "dark" else BLUE_LAGOON

    return f'''
    QWidget {{
        color: {t.text};
        font-family: "{FONT_FAMILY}";
        font-size: 11pt;
    }}

    QMainWindow, QDialog, QWizard, QWizardPage {{
        background: {t.background};
        color: {t.text};
    }}

    QWidget#content, QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollArea {{ border: none; }}

    QLabel {{
        background: transparent;
        border: none;
        color: {t.text};
    }}
    QLabel[role="eyebrow"] {{
        color: {t.accent_text};
        font-size: 10pt;
        font-weight: 700;
    }}
    QLabel[role="title"] {{
        color: {t.text};
        font-size: 24pt;
        font-weight: 700;
    }}
    QLabel[role="pageTitle"] {{
        color: {t.text};
        font-size: 21pt;
        font-weight: 700;
    }}
    QLabel[role="heading"] {{
        color: {t.text};
        font-size: 15pt;
        font-weight: 650;
    }}
    QLabel[role="muted"] {{
        color: {t.muted};
        font-size: 11pt;
    }}
    QLabel[role="metric"] {{
        color: {t.text};
        font-size: 25pt;
        font-weight: 650;
    }}
    QLabel[role="error"] {{
        color: {t.error};
        background: transparent;
        font-size: 10pt;
        font-weight: 600;
        padding: 2px 0px;
    }}

    QFrame[role="card"] {{
        background: {t.glass};
        border: 1px solid {t.border};
        border-radius: 14px;
    }}
    QFrame[role="glass"] {{
        background: {t.glass};
        border: 1px solid {t.border};
        border-radius: 14px;
    }}
    QFrame#logoPlate {{
        background: {ALABASTER};
        border-radius: 10px;
    }}

    QPushButton {{
        background: {t.surface};
        color: {t.text};
        border: 2px solid {t.border};
        border-radius: 8px;
        padding: 9px 15px;
        font-size: 11pt;
        font-weight: 600;
        min-height: 20px;
    }}
    QPushButton:hover {{
        background: {t.selected};
        border-color: {SCOOTER};
    }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton:checked {{
        background: {t.selected};
        border-color: {SCOOTER};
        color: {t.accent_text};
    }}
    QPushButton[role="primary"] {{
        color: white;
        border-color: {BLUE_LAGOON};
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {BLUE_LAGOON},
            stop:1 {SAPPHIRE}
        );
    }}
    QPushButton[role="primary"]:hover {{
        background: {BLUE_LAGOON};
        border-color: {SCOOTER};
    }}
    QPushButton[role="primary"]:pressed {{ background: {SAPPHIRE}; }}
    QPushButton:disabled {{
        background: {t.background};
        color: {t.muted};
        border-color: {t.border};
    }}
    QPushButton:focus {{ border-color: {SCOOTER}; }}

    QLineEdit, QComboBox, QDateEdit, QTimeEdit, QTextEdit, QPlainTextEdit {{
        background: {t.field};
        color: {t.text};
        border: 2px solid {t.border};
        border-radius: 8px;
        padding: 9px;
        min-height: 22px;
        font-size: 11pt;
        selection-background-color: {BLUE_LAGOON};
        selection-color: white;
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {SCOOTER}; }}
    QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
        background: {t.background};
        color: {t.muted};
    }}

    /* QTimeEdit is a QAbstractSpinBox. Without explicit styling Windows can
       keep its native light spin-button area even while ChitLog is in dark mode. */
    QTimeEdit::up-button, QTimeEdit::down-button {{
        subcontrol-origin: border;
        width: 24px;
        background: {t.surface};
        border-left: 1px solid {t.border};
    }}
    QTimeEdit::up-button {{
        subcontrol-position: top right;
        border-top-right-radius: 7px;
        border-bottom: 1px solid {t.border};
    }}
    QTimeEdit::down-button {{
        subcontrol-position: bottom right;
        border-bottom-right-radius: 7px;
    }}
    QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{
        background: {t.selected};
    }}
    QComboBox QAbstractItemView {{
        background: {t.surface};
        color: {t.text};
        selection-background-color: {t.selected};
        selection-color: {t.text};
        border: 1px solid {t.border};
    }}

    QMenu {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.border};
        padding: 5px;
    }}
    QMenu::item {{
        color: {t.text};
        background: transparent;
        padding: 7px 18px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        color: {t.text};
        background: {t.selected};
    }}
    QMenu::separator {{
        height: 1px;
        background: {t.border};
        margin: 4px 8px;
    }}

    QTabWidget#workerTabs::pane {{
        background: transparent;
        border: 1px solid {t.border};
        border-radius: 12px;
        top: -1px;
    }}
    QTabWidget#workerTabs QTabBar::tab {{
        background: {t.glass};
        color: {t.muted};
        border: 1px solid {t.border};
        border-bottom: none;
        border-top-left-radius: 9px;
        border-top-right-radius: 9px;
        padding: 9px 18px;
        margin-right: 4px;
        font-weight: 600;
    }}
    QTabWidget#workerTabs QTabBar::tab:hover {{
        background: {t.selected};
        color: {t.text};
        border-color: {SCOOTER};
    }}
    QTabWidget#workerTabs QTabBar::tab:selected {{
        background: {t.selected};
        color: {t.accent_text};
        border-color: {SCOOTER};
    }}

    QTabBar#workerFixedTabs {{
        background: transparent;
        border: none;
    }}
    QTabBar#workerFixedTabs::tab {{
        background: {t.glass};
        color: {t.muted};
        border: 1px solid {t.border};
        border-radius: 9px;
        padding: 8px 18px;
        margin-right: 5px;
        font-weight: 600;
    }}
    QTabBar#workerFixedTabs::tab:hover {{
        background: {t.selected};
        color: {t.text};
        border-color: {SCOOTER};
    }}
    QTabBar#workerFixedTabs::tab:selected {{
        background: {t.selected};
        color: {t.accent_text};
        border-color: {SCOOTER};
    }}
    QTabBar#workerFixedTabs[responsiveCompact="true"]::tab {{
        padding: 7px 8px;
        margin-right: 2px;
        font-size: 9.5pt;
        min-width: 0px;
    }}

    QTableWidget#payrollSummaryTable[responsiveCompact="true"] {{
        font-size: 9.5pt;
    }}
    QTableWidget#payrollSummaryTable[responsiveCompact="true"]::item {{
        padding: 4px;
    }}
    QTableWidget#payrollSummaryTable[responsiveCompact="true"] QHeaderView::section {{
        padding: 5px 3px;
        font-size: 9pt;
    }}

    QTableWidget, QListWidget {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 10px;
        gridline-color: {t.border};
        selection-background-color: {t.selected};
        selection-color: {t.text};
    }}
    QTableWidget::item, QListWidget::item {{
        padding: 7px;
    }}
    QHeaderView::section {{
        background: {t.field};
        color: {t.text};
        border: none;
        border-bottom: 1px solid {t.border};
        padding: 8px;
        font-weight: 650;
    }}

    QRadioButton, QCheckBox {{
        color: {t.text};
        spacing: 10px;
        padding: 5px 2px;
        font-size: 12pt;
        border: none;
        background: transparent;
    }}
    QRadioButton:focus, QCheckBox:focus {{
        border: none;
        background: transparent;
    }}
    QRadioButton::indicator, QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1px solid {t.border};
        background: {t.field};
    }}
    QRadioButton::indicator {{ border-radius: 9px; }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator:checked {{
        background: {BLUE_LAGOON};
        border: 3px solid {SCOOTER};
    }}
    QCheckBox::indicator:checked {{
        background: {BLUE_LAGOON};
        border: 2px solid {SCOOTER};
        image: url("{checkmark_path}");
    }}

    /* Salary-slip selection uses item-view checkboxes rather than QCheckBox.
       Keep the empty box clearly visible in dark mode without overriding the
       platform's existing white checked tick. */
    QTableWidget#workersPayrollTable::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 3px;
    }}
    QTableWidget#workersPayrollTable::indicator:unchecked {{
        border: 2px solid {payroll_checkbox_border};
        background: {t.field};
    }}
    QTableWidget#workersPayrollTable::indicator:checked {{
        border: 2px solid {payroll_checkbox_border};
        background: {BLUE_LAGOON};
        image: url("{checkmark_path}");
    }}

    QToolButton {{
        background: {t.surface};
        color: {t.text};
        border: 2px solid {t.border};
        border-radius: 8px;
        min-width: 38px;
        min-height: 38px;
        padding: 2px;
        font-size: 12pt;
    }}
    QToolButton:hover {{
        background: {t.selected};
        border-color: {SCOOTER};
    }}
    QToolButton:focus {{ border-color: {SCOOTER}; }}
    QToolButton:checked {{
        background: {t.selected};
        border-color: {SCOOTER};
    }}

    QToolButton[role="nav"] {{
        background: transparent;
        color: {t.text};
        border: 2px solid transparent;
        border-radius: 10px;
        min-height: 42px;
        padding: 7px 9px;
        text-align: left;
        font-size: 11pt;
        font-weight: 600;
    }}
    QToolButton[role="nav"]:hover {{
        background: {t.selected};
        border-color: {t.border};
    }}
    QToolButton[role="nav"]:focus {{
        border-color: {SCOOTER};
    }}
    QToolButton[role="nav"]:checked {{
        background: {t.selected};
        color: {t.accent_text};
        border-color: {SCOOTER};
    }}

    QLabel[role="navBadge"] {{
        background: {t.accent_text};
        color: {t.surface};
        border: none;
        border-radius: 10px;
        padding: 0px 4px;
        font-size: 9pt;
        font-weight: 700;
    }}

    QToolButton[role="sidebarToggle"] {{
        background: transparent;
        border: 2px solid transparent;
    }}
    QToolButton[role="sidebarToggle"]:hover,
    QToolButton[role="sidebarToggle"]:focus {{
        background: {t.selected};
        border-color: {SCOOTER};
    }}

    QProgressBar {{
        background: {t.selected};
        border: none;
        border-radius: 4px;
        max-height: 8px;
    }}
    QProgressBar::chunk {{
        background: {SCOOTER};
        border-radius: 4px;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t.border};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{ height: 0; }}



    /* Responsive button density for narrow application windows.
       Existing filter-specific compact styles below remain more specific and
       continue to control filter rows. */
    QPushButton[responsiveCompact="true"] {{
        font-size: 9.5pt;
        padding: 6px 10px;
        min-height: 18px;
        border-radius: 7px;
    }}
    QToolButton[responsiveCompact="true"] {{
        font-size: 10pt;
        min-width: 32px;
        min-height: 32px;
        padding: 2px;
    }}

    QToolButton[timeStepper="true"] {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 4px;
        padding: 0px;
        margin: 0px;
        min-width: 0px;
        min-height: 0px;
        font-size: 7pt;
        font-weight: 700;
    }}
    QToolButton[timeStepper="true"]:hover {{
        background: {t.selected};
        border-color: {SCOOTER};
    }}
    QToolButton[timeStepper="true"]:pressed {{
        background: {t.border};
    }}

    /* Compact controls are used only inside record-filter rows. */
    QLabel[compact="true"] {{
        font-size: 9pt;
    }}
    QComboBox[compact="true"],
    QLineEdit[compact="true"],
    QDateEdit[compact="true"],
    QTimeEdit[compact="true"] {{
        font-size: 9.5pt;
        padding: 5px 7px;
        min-height: 18px;
        border-radius: 7px;
    }}
    QPushButton[compact="true"] {{
        font-size: 9.5pt;
        padding: 5px 10px;
        min-height: 18px;
        border-radius: 7px;
    }}
    QCheckBox[compact="true"],
    QRadioButton[compact="true"] {{
        font-size: 9.5pt;
        spacing: 7px;
        padding: 2px;
    }}
    QCheckBox[compact="true"]::indicator,
    QRadioButton[compact="true"]::indicator {{
        width: 15px;
        height: 15px;
    }}

    QPushButton[role="danger"] {{
        color: white;
        background: #B83C4A;
        border-color: #B83C4A;
    }}
    QPushButton[role="danger"]:hover {{
        background: #9E303E;
        border-color: #9E303E;
    }}

    /* QDateEdit opens a QCalendarWidget in a separate popup. Native Windows
       calendar colors do not automatically follow our dark palette, so style
       every calendar surface explicitly. */
    QCalendarWidget {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.border};
    }}
    QCalendarWidget QWidget {{
        background: {t.surface};
        color: {t.text};
        alternate-background-color: {t.field};
    }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{
        background: {t.field};
        border-bottom: 1px solid {t.border};
    }}
    QCalendarWidget QToolButton {{
        background: transparent;
        color: {t.text};
        border: 1px solid transparent;
        min-width: 24px;
        min-height: 24px;
        padding: 4px 6px;
        font-size: 10pt;
    }}
    QCalendarWidget QToolButton:hover {{
        background: {t.selected};
        border-color: {SCOOTER};
    }}
    QCalendarWidget QSpinBox {{
        background: {t.field};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 3px 27px 3px 7px;
        min-height: 22px;
        selection-background-color: {BLUE_LAGOON};
        selection-color: white;
    }}
    QCalendarWidget QSpinBox::up-button,
    QCalendarWidget QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 22px;
        background: {t.surface};
        border-left: 1px solid {t.border};
    }}
    QCalendarWidget QSpinBox::up-button {{
        subcontrol-position: top right;
        border-top-right-radius: 5px;
        border-bottom: 1px solid {t.border};
    }}
    QCalendarWidget QSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-bottom-right-radius: 5px;
    }}
    QCalendarWidget QSpinBox::up-button:hover,
    QCalendarWidget QSpinBox::down-button:hover {{
        background: {t.selected};
        border-left-color: {SCOOTER};
    }}
    QCalendarWidget QAbstractItemView:enabled {{
        background: {t.surface};
        color: {t.text};
        selection-background-color: {SCOOTER};
        selection-color: white;
        outline: 0;
    }}
    QCalendarWidget QAbstractItemView:item:hover {{
        background: {t.selected};
        color: {t.text};
    }}
    QCalendarWidget QAbstractItemView:disabled {{
        color: {t.muted};
    }}

    QToolTip {{
        background: {t.surface};
        color: {t.text};
        border: 1px solid {t.border};
        padding: 6px;
    }}

    QGroupBox {{
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 12px;
        margin-top: 12px;
        padding: 14px;
        font-weight: 600;
    }}
    '''
