"""Tests for first-run setup persistence and security helpers."""
import secrets

import pytest

from chitlog.core.security import (
    SecurityError,
    SecurityQuestionAnswer,
    verify_secret,
    verify_security_answer,
)
from chitlog.core.settings import AppearanceSettings
from chitlog.data.database import Database
from chitlog.data.setup_repository import SetupRepository
from chitlog.services.setup_service import SetupService, SetupSubmission


@pytest.fixture
def db(tmp_path):
    instance = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    yield instance
    instance.close()


def test_setup_persists_hashes_currency_and_theme(db, tmp_path):
    appearance = AppearanceSettings(tmp_path / "appearance.json")
    repository = SetupRepository(db)
    service = SetupService(repository, appearance)

    service.complete_setup(
        SetupSubmission(
            login_method="pin",
            secret="123456",
            confirmation="123456",
            security_questions=[
                SecurityQuestionAnswer("Private phrase?", "Blue River"),
                SecurityQuestionAnswer("Memorable place?", "Kandy Lake"),
            ],
            currency_code="LKR",
            theme="dark",
        )
    )

    assert repository.is_setup_complete() is True
    state = repository.load_state()
    assert state.currency_code == "LKR"
    assert state.currency_symbol == "Rs"
    assert state.theme == "dark"
    assert appearance.load_theme() == "dark"

    method, secret_hash = db.connection.execute(
        "SELECT login_method, secret_hash FROM auth_profile WHERE id=1"
    ).fetchone()
    assert method == "pin"
    assert secret_hash != "123456"
    assert secret_hash.startswith("$argon2id$")
    assert verify_secret(secret_hash, "123456") is True
    assert verify_secret(secret_hash, "654321") is False

    questions = db.connection.execute(
        "SELECT question, answer_hash FROM security_questions ORDER BY position"
    ).fetchall()
    assert len(questions) == 2
    assert questions[0][1] != "Blue River"
    assert questions[0][1].startswith("$argon2id$")
    assert verify_security_answer(questions[0][1], " blue   river ") is True
    assert verify_security_answer(questions[0][1], "wrong") is False


def test_setup_requires_exactly_two_questions(db, tmp_path):
    service = SetupService(
        SetupRepository(db),
        AppearanceSettings(tmp_path / "appearance.json"),
    )

    with pytest.raises(SecurityError):
        service.complete_setup(
            SetupSubmission(
                login_method="password",
                secret="examplepass",
                confirmation="examplepass",
                security_questions=[
                    SecurityQuestionAnswer("Only one?", "answer"),
                ],
                currency_code="USD",
                theme="light",
            )
        )

    assert SetupRepository(db).is_setup_complete() is False


def test_setup_rejects_duplicate_questions(db, tmp_path):
    service = SetupService(
        SetupRepository(db),
        AppearanceSettings(tmp_path / "appearance.json"),
    )

    with pytest.raises(SecurityError):
        service.complete_setup(
            SetupSubmission(
                login_method="pin",
                secret="1234",
                confirmation="1234",
                security_questions=[
                    SecurityQuestionAnswer("Same question", "one"),
                    SecurityQuestionAnswer("same question", "two"),
                ],
                currency_code="LKR",
                theme="system",
            )
        )


def test_setup_rejects_invalid_pin_and_mismatch(db, tmp_path):
    service = SetupService(
        SetupRepository(db),
        AppearanceSettings(tmp_path / "appearance.json"),
    )
    questions = [
        SecurityQuestionAnswer("Question one", "Answer one"),
        SecurityQuestionAnswer("Question two", "Answer two"),
    ]

    with pytest.raises(SecurityError):
        service.complete_setup(
            SetupSubmission(
                login_method="pin",
                secret="12ab",
                confirmation="12ab",
                security_questions=questions,
                currency_code="USD",
                theme="light",
            )
        )

    with pytest.raises(SecurityError):
        service.complete_setup(
            SetupSubmission(
                login_method="password",
                secret="longpassword",
                confirmation="differentpass",
                security_questions=questions,
                currency_code="USD",
                theme="light",
            )
        )
