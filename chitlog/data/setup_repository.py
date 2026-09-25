"""Database persistence for the first-run setup wizard."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class StoredSetupQuestion:
    position: int
    question: str
    answer_hash: str


@dataclass(frozen=True)
class SetupState:
    is_complete: bool
    theme: str | None
    currency_code: str | None
    currency_symbol: str | None


class SetupRepository:
    def __init__(self, database: Database):
        self.database = database

    def _get_setting(self, key: str) -> str | None:
        row = self.database.connection.execute(
            "SELECT value FROM application_settings WHERE key=?",
            (key,),
        ).fetchone()
        return row[0] if row else None

    def is_setup_complete(self) -> bool:
        return self._get_setting("setup_complete") == "true"

    def load_state(self) -> SetupState:
        return SetupState(
            is_complete=self.is_setup_complete(),
            theme=self._get_setting("theme"),
            currency_code=self._get_setting("currency_code"),
            currency_symbol=self._get_setting("currency_symbol"),
        )

    def update_theme(self, theme: str) -> None:
        """Persist the currently selected application theme in encrypted settings."""
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO application_settings(key, value) VALUES ('theme', ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (theme,),
            )

    def save_setup(
        self,
        *,
        login_method: str,
        secret_hash: str,
        questions: list[StoredSetupQuestion],
        currency_code: str,
        currency_symbol: str,
        theme: str,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM auth_profile")
            connection.execute(
                "INSERT INTO auth_profile(id, login_method, secret_hash) "
                "VALUES (1, ?, ?)",
                (login_method, secret_hash),
            )

            connection.execute("DELETE FROM security_questions")
            connection.executemany(
                "INSERT INTO security_questions(position, question, answer_hash) "
                "VALUES (?, ?, ?)",
                [(q.position, q.question, q.answer_hash) for q in questions],
            )

            settings = (
                ("currency_code", currency_code),
                ("currency_symbol", currency_symbol),
                ("theme", theme),
                ("setup_complete", "true"),
            )
            connection.executemany(
                "INSERT INTO application_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                settings,
            )
