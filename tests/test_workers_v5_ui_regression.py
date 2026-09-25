from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_permanent_delete_history_explains_and_offers_deactivate():
    source = read("chitlog/ui/pages/workers.py")
    assert "Worker Cannot Be Permanently Deleted" in source
    assert "Deactivate this worker instead?" in source
    assert 'button("Deactivate Worker", "primary")' in source
    assert "Financial history was kept safely" in source


def test_worker_date_fields_use_shared_reliable_calendar():
    date_picker = read("chitlog/ui/date_picker.py")
    workers = read("chitlog/ui/pages/workers.py")
    work = read("chitlog/ui/pages/worker_work_records.py")
    payments = read("chitlog/ui/pages/worker_payments.py")
    assert "QCalendarWidget" in date_picker
    assert "qt_calendar_yearedit" in date_picker
    assert "calendar.clicked.connect(field.setDate)" in date_picker
    assert "field.dateChanged.connect(calendar.setSelectedDate)" in date_picker
    assert "configure_date_edit(" in workers
    assert work.count("configure_date_edit(") >= 3
    assert "configure_date_edit(" in payments


def test_dark_summary_cards_follow_chitlog_theme_and_overlay_restores():
    source = read("chitlog/ui/step23_polish.py")
    assert 'configured = getattr(root, "theme_name", None)' in source
    assert "theme_value = resolve_theme(configured)" in source
    assert '"CHITLOG_STEP23_OVERLAY" not in current_css' in source
    assert "stop:0 #071F31" in source
    assert "color: #A6F2E9" in source


def test_calendar_year_spin_buttons_are_explicitly_styled():
    theme = read("chitlog/ui/theme.py")
    assert "QCalendarWidget QSpinBox::up-button" in theme
    assert "QCalendarWidget QSpinBox::down-button" in theme
