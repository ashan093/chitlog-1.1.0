"""Bounded fixed-event logging; user values and exception text are rejected."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


EVENTS = frozenset(
    {
        "application_started",
        "application_stopped",
        "startup_failed",
        "setup_cancelled",
        "login_cancelled",
        "pre_restore_recovery_completed",
    }
)


class EventFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return (
            isinstance(record.msg, str)
            and record.msg in EVENTS
            and not record.args
            and not record.exc_info
            and not record.stack_info
        )


def configure_logging(folder: Path) -> logging.Logger:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("chitlog.events")
    close_logging(logger)

    handler = RotatingFileHandler(
        folder / "chitlog.log",
        maxBytes=1_048_576,
        backupCount=3,
        encoding="utf-8",
        errors="backslashreplace",
    )
    handler.addFilter(EventFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.disabled = False
    return logger


def close_logging(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
