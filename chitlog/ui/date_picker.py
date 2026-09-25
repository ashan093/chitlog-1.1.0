"""Shared, reliable calendar configuration for ChitLog date fields."""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QAbstractSpinBox, QCalendarWidget, QDateEdit, QSpinBox


def configure_date_edit(
    field: QDateEdit,
    *,
    minimum: QDate | None = None,
    maximum: QDate | None = None,
) -> QCalendarWidget:
    """Attach an explicitly configured calendar popup to a QDateEdit.

    Qt can create the calendar lazily. Giving each ChitLog date field its own
    calendar keeps day clicks, month/year navigation and the year spin control
    synchronized across Windows styles and Light/Dark/System themes.
    """
    field.setCalendarPopup(True)
    field.setDisplayFormat("yyyy-MM-dd")
    field.setKeyboardTracking(False)
    field.setAccelerated(True)

    if minimum is not None and minimum.isValid():
        field.setMinimumDate(minimum)
    if maximum is not None and maximum.isValid():
        field.setMaximumDate(maximum)

    calendar = QCalendarWidget(field)
    calendar.setNavigationBarVisible(True)
    calendar.setGridVisible(True)
    calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
    calendar.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
    calendar.setDateEditEnabled(True)
    calendar.setDateEditAcceptDelay(350)
    calendar.setMinimumDate(field.minimumDate())
    calendar.setMaximumDate(field.maximumDate())
    calendar.setSelectedDate(field.date())

    # Explicit two-way synchronization avoids platform/style-specific cases in
    # which the popup changes its current cell but QDateEdit keeps the old date.
    calendar.clicked.connect(field.setDate)
    calendar.activated.connect(field.setDate)
    field.dateChanged.connect(calendar.setSelectedDate)

    field.setCalendarWidget(calendar)

    year_edit = calendar.findChild(QSpinBox, "qt_calendar_yearedit")
    if year_edit is not None:
        year_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        year_edit.setAccelerated(True)
        year_edit.setWrapping(False)
        year_edit.setMinimum(field.minimumDate().year())
        year_edit.setMaximum(field.maximumDate().year())

    field.setToolTip(
        f"Choose a date from {field.minimumDate().toString('yyyy-MM-dd')} "
        f"through {field.maximumDate().toString('yyyy-MM-dd')}."
    )
    return calendar
