"""Authentication and recovery business logic."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.core.security import (
    hash_secret,
    validate_secret,
    verify_secret,
    verify_security_answer,
)
from chitlog.data.authentication_repository import AuthenticationRepository


@dataclass(frozen=True)
class PublicRecoveryQuestion:
    position: int
    question: str


class AuthenticationService:
    """Central authority for login and credential recovery.

    No attempt counter or account lockout is maintained. A failed verification
    simply returns False so the user may try again immediately.
    """

    def __init__(self, repository: AuthenticationRepository):
        self.repository = repository

    def login_method(self) -> str:
        return self.repository.load_profile().login_method

    def verify_login(self, candidate: str) -> bool:
        profile = self.repository.load_profile()
        if not candidate:
            return False
        return verify_secret(profile.secret_hash, candidate)

    def recovery_questions(self) -> list[PublicRecoveryQuestion]:
        questions = self.repository.load_recovery_questions()
        if len(questions) != 2:
            raise RuntimeError("Account recovery is not configured correctly.")
        return [
            PublicRecoveryQuestion(position=item.position, question=item.question)
            for item in questions
        ]

    def verify_recovery_answers(self, answers: list[str]) -> bool:
        questions = self.repository.load_recovery_questions()
        if len(questions) != 2 or len(answers) != 2:
            return False
        return all(
            verify_security_answer(question.answer_hash, answer)
            for question, answer in zip(questions, answers, strict=True)
        )

    def reset_credentials(
        self,
        login_method: str,
        new_secret: str,
        confirmation: str,
    ) -> None:
        """Reset the secret and optionally switch between PIN and Password."""
        validate_secret(login_method, new_secret, confirmation)
        self.repository.update_credentials(
            login_method,
            hash_secret(login_method, new_secret),
        )

    def reset_secret(self, new_secret: str, confirmation: str) -> None:
        """Keep the current login method; retained for internal compatibility."""
        self.reset_credentials(self.login_method(), new_secret, confirmation)
