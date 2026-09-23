"""Authentication and recovery tests use only disposable encrypted databases."""
import secrets

import pytest

from chitlog.core.security import SecurityError, SecurityQuestionAnswer
from chitlog.core.settings import AppearanceSettings
from chitlog.data.authentication_repository import AuthenticationRepository
from chitlog.data.database import Database
from chitlog.data.setup_repository import SetupRepository
from chitlog.services.authentication_service import AuthenticationService
from chitlog.services.setup_service import SetupService, SetupSubmission


@pytest.fixture
def auth(tmp_path):
    database = Database(
        tmp_path / "test.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    setup = SetupService(
        SetupRepository(database),
        AppearanceSettings(tmp_path / "appearance.json"),
    )
    setup.complete_setup(
        SetupSubmission(
            login_method="pin",
            secret="2468",
            confirmation="2468",
            security_questions=[
                SecurityQuestionAnswer("First private question?", "Blue River"),
                SecurityQuestionAnswer("Second private question?", "Kandy Lake"),
            ],
            currency_code="LKR",
            theme="dark",
        )
    )
    service = AuthenticationService(AuthenticationRepository(database))
    yield database, service
    database.close()


def test_correct_and_incorrect_login_have_unlimited_normal_retries(auth):
    _, service = auth
    for _ in range(20):
        assert service.verify_login("0000") is False
    assert service.verify_login("2468") is True
    assert service.verify_login("0000") is False
    assert service.verify_login("2468") is True


def test_recovery_questions_expose_questions_not_hashes(auth):
    database, service = auth
    public = service.recovery_questions()
    assert [item.question for item in public] == [
        "First private question?",
        "Second private question?",
    ]
    hashes = database.connection.execute(
        "SELECT answer_hash FROM security_questions ORDER BY position"
    ).fetchall()
    assert all(item[0].startswith("$argon2id$") for item in hashes)
    assert all(item[0] not in {"Blue River", "Kandy Lake"} for item in hashes)


def test_recovery_normalization_and_wrong_answers(auth):
    _, service = auth
    assert service.verify_recovery_answers([" blue   river ", "KANDY LAKE"]) is True
    assert service.verify_recovery_answers(["wrong", "Kandy Lake"]) is False
    assert service.verify_recovery_answers(["Blue River", "wrong"]) is False
    assert service.verify_recovery_answers(["Blue River"]) is False


def test_reset_secret_replaces_hash_and_old_pin_stops_working(auth):
    database, service = auth
    old_hash = database.connection.execute(
        "SELECT secret_hash FROM auth_profile WHERE id=1"
    ).fetchone()[0]

    service.reset_secret("1357", "1357")

    profile = database.connection.execute(
        "SELECT login_method, secret_hash FROM auth_profile WHERE id=1"
    ).fetchone()
    assert profile[0] == "pin"
    assert profile[1].startswith("$argon2id$")
    assert profile[1] != old_hash
    assert "1357" not in profile[1]
    assert service.verify_login("2468") is False
    assert service.verify_login("1357") is True


def test_recovery_can_switch_from_pin_to_password(auth):
    database, service = auth
    service.reset_credentials("password", "new-password-123", "new-password-123")

    method, stored_hash = database.connection.execute(
        "SELECT login_method, secret_hash FROM auth_profile WHERE id=1"
    ).fetchone()
    assert method == "password"
    assert stored_hash.startswith("$argon2id$")
    assert "new-password-123" not in stored_hash
    assert service.login_method() == "password"
    assert service.verify_login("2468") is False
    assert service.verify_login("new-password-123") is True


def test_reset_rejects_mismatch_and_invalid_pin_without_changing_profile(auth):
    database, service = auth
    before = database.connection.execute(
        "SELECT login_method, secret_hash FROM auth_profile WHERE id=1"
    ).fetchone()

    with pytest.raises(SecurityError):
        service.reset_credentials("pin", "1234", "4321")
    with pytest.raises(SecurityError):
        service.reset_credentials("pin", "12", "12")
    with pytest.raises(SecurityError):
        service.reset_credentials("password", "short", "short")

    after = database.connection.execute(
        "SELECT login_method, secret_hash FROM auth_profile WHERE id=1"
    ).fetchone()
    assert after == before


def test_theme_setting_can_be_updated_after_setup(auth):
    database, _ = auth
    repository = SetupRepository(database)
    assert repository.load_state().theme == "dark"
    repository.update_theme("light")
    assert repository.load_state().theme == "light"
