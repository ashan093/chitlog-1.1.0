"""Database access for login and account recovery."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class AuthenticationProfile:
    login_method: str
    secret_hash: str


@dataclass(frozen=True)
class RecoveryQuestion:
    position: int
    question: str
    answer_hash: str


class AuthenticationRepository:
    def __init__(self, database: Database):
        self.database = database

    def load_profile(self) -> AuthenticationProfile:
        row = self.database.connection.execute(
            "SELECT login_method, secret_hash FROM auth_profile WHERE id=1"
        ).fetchone()
        if row is None:
            raise RuntimeError("Authentication is not configured.")
        return AuthenticationProfile(login_method=row[0], secret_hash=row[1])

    def load_recovery_questions(self) -> list[RecoveryQuestion]:
        rows = self.database.connection.execute(
            "SELECT position, question, answer_hash "
            "FROM security_questions ORDER BY position"
        ).fetchall()
        return [RecoveryQuestion(*row) for row in rows]

    def update_credentials(self, login_method: str, secret_hash: str) -> None:
        """Atomically replace both login method and hashed secret."""
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE auth_profile "
                "SET login_method=?, secret_hash=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=1",
                (login_method, secret_hash),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Authentication is not configured.")

    def update_secret(self, secret_hash: str) -> None:
        """Compatibility helper for callers that keep the existing login method."""
        profile = self.load_profile()
        self.update_credentials(profile.login_method, secret_hash)
