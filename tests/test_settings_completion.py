"""Step 20 Settings repository/service behavior."""
import secrets

import pytest

from chitlog.core.security import SecurityQuestionAnswer, verify_secret, verify_security_answer
from chitlog.data.database import Database
from chitlog.data.settings_repository import SettingsRepository
from chitlog.services.settings_service import SettingsError, SettingsService


def make_db(tmp_path):
    db = Database(
        tmp_path / "settings.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO auth_profile(id,login_method,secret_hash) VALUES "
            "(1,'password',?)",
            (
                "$argon2id$v=19$m=65536,t=3,p=4$"
                "MDEyMzQ1Njc4OWFiY2RlZg$"
                "yWfhVXAM1PMaq5fnMMwFT5g2gO2NnrDgRTeu1J8BzXM",
            ),
        )
    return db


def configure_real_auth(db):
    from chitlog.core.security import hash_secret, hash_security_answer

    with db.transaction() as connection:
        connection.execute("DELETE FROM auth_profile")
        connection.execute("DELETE FROM security_questions")
        connection.execute(
            "INSERT INTO auth_profile(id,login_method,secret_hash) VALUES (1,'password',?)",
            (hash_secret("password", "old-password"),),
        )
        connection.executemany(
            "INSERT INTO security_questions(position,question,answer_hash) VALUES (?,?,?)",
            [
                (1, "Old question one?", hash_security_answer("alpha")),
                (2, "Old question two?", hash_security_answer("beta")),
            ],
        )
        connection.executemany(
            "INSERT INTO application_settings(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [
                ("theme", "dark"),
                ("currency_code", "LKR"),
                ("currency_symbol", "Rs"),
                ("setup_complete", "true"),
            ],
        )


def test_settings_load_and_same_precision_currency_change_preserves_money(tmp_path):
    db = Database(
        tmp_path / "settings.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        configure_real_auth(db)
        with db.transaction() as connection:
            category_id = connection.execute(
                "INSERT INTO categories(kind,name) VALUES ('expense','Step20 Currency')"
            ).lastrowid
            connection.execute(
                "INSERT INTO transactions(transaction_type,transaction_date,amount_minor,category_id) "
                "VALUES ('expense','2026-09-18',123456,?)",
                (category_id,),
            )

        service = SettingsService(SettingsRepository(db))
        before = db.connection.execute(
            "SELECT amount_minor FROM transactions"
        ).fetchone()[0]

        changed = service.change_currency("USD")
        assert changed.code == "USD"
        snapshot = service.snapshot()
        assert snapshot.currency_code == "USD"
        assert snapshot.currency_symbol == "$"

        after = db.connection.execute(
            "SELECT amount_minor FROM transactions"
        ).fetchone()[0]
        assert after == before
    finally:
        db.close()


def test_settings_blocks_precision_change_after_financial_records_exist(tmp_path):
    db = Database(
        tmp_path / "settings.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        configure_real_auth(db)
        with db.transaction() as connection:
            category_id = connection.execute(
                "INSERT INTO categories(kind,name) VALUES ('expense','JPY Guard')"
            ).lastrowid
            connection.execute(
                "INSERT INTO transactions(transaction_type,transaction_date,amount_minor,category_id) "
                "VALUES ('expense','2026-09-18',10000,?)",
                (category_id,),
            )

        service = SettingsService(SettingsRepository(db))
        with pytest.raises(SettingsError, match="different decimal precision"):
            service.change_currency("JPY")

        assert service.snapshot().currency_code == "LKR"
    finally:
        db.close()


def test_settings_allows_precision_change_before_financial_records_exist(tmp_path):
    db = Database(
        tmp_path / "settings.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        configure_real_auth(db)
        service = SettingsService(SettingsRepository(db))
        changed = service.change_currency("JPY")
        assert changed.code == "JPY"
        assert service.snapshot().currency_code == "JPY"
    finally:
        db.close()


def test_change_credentials_requires_current_secret_and_stores_only_hash(tmp_path):
    db = Database(
        tmp_path / "settings.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        configure_real_auth(db)
        service = SettingsService(SettingsRepository(db))

        with pytest.raises(SettingsError, match="incorrect"):
            service.change_credentials(
                current_secret="wrong-password",
                login_method="pin",
                new_secret="2468",
                confirmation="2468",
            )

        saved = service.change_credentials(
            current_secret="old-password",
            login_method="pin",
            new_secret="2468",
            confirmation="2468",
        )
        assert saved == "pin"

        row = db.connection.execute(
            "SELECT login_method,secret_hash FROM auth_profile WHERE id=1"
        ).fetchone()
        assert row[0] == "pin"
        assert row[1] != "2468"
        assert verify_secret(row[1], "2468")
    finally:
        db.close()


def test_change_recovery_questions_requires_current_secret_and_hashes_answers(tmp_path):
    db = Database(
        tmp_path / "settings.db",
        secrets.token_bytes(32),
        tmp_path / "snapshots",
    ).open()
    try:
        configure_real_auth(db)
        service = SettingsService(SettingsRepository(db))

        saved = service.change_recovery_questions(
            current_secret="old-password",
            questions=[
                SecurityQuestionAnswer("New first question?", "Secret One"),
                SecurityQuestionAnswer("New second question?", "Secret Two"),
            ],
        )
        assert saved == ("New first question?", "New second question?")

        rows = db.connection.execute(
            "SELECT question,answer_hash FROM security_questions ORDER BY position"
        ).fetchall()
        assert rows[0][0] == "New first question?"
        assert rows[0][1] != "Secret One"
        assert verify_security_answer(rows[0][1], "secret one")
        assert rows[1][1] != "Secret Two"
        assert verify_security_answer(rows[1][1], "SECRET TWO")
    finally:
        db.close()
