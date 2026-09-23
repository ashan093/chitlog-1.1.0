"""Step 22 privacy-safe logging checks."""
import logging

from chitlog.core.logging_config import close_logging, configure_logging


def test_logging_accepts_only_fixed_events_and_never_user_values(tmp_path):
    logger = configure_logging(tmp_path / "logs")
    try:
        logger.info("application_started")
        logger.info("private balance: 999999")
        logger.error("startup_failed", exc_info=RuntimeError("private exception"))
        logger.info("login_cancelled")

        for handler in logger.handlers:
            handler.flush()

        text = (tmp_path / "logs/chitlog.log").read_text(encoding="utf-8")
        assert "application_started" in text
        assert "login_cancelled" in text
        assert "private balance" not in text
        assert "private exception" not in text
        # exc_info records are rejected even when their event name is approved.
        assert "startup_failed" not in text
    finally:
        close_logging(logger)
