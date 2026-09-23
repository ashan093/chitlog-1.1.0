"""Step 20 startup-path performance regression checks."""
from pathlib import Path


def test_scheduler_sync_is_deferred_until_after_window_show():
    project = Path(__file__).resolve().parents[1]
    source = (project / "chitlog/application.py").read_text(encoding="utf-8")

    show_index = source.index("window.show()")
    deferred_comment_index = source.index(
        "# Windows Task Scheduler can take noticeable time on some PCs."
    )
    timer_index = source.index(
        "QTimer.singleShot(\n                1200,",
        deferred_comment_index,
    )
    service_setup_index = source.index(
        "notification_service = NotificationService("
    )

    assert service_setup_index < show_index
    assert show_index < deferred_comment_index < timer_index
    assert "_sync_notification_task_after_startup(service)" in source[timer_index:]
