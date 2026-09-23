"""Credential and recovery-answer hashing helpers for local authentication."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


MAX_CREDENTIAL_INPUT_LENGTH = 128
MAX_SECURITY_ANSWER_LENGTH = 200
MAX_ENCODED_HASH_LENGTH = 512

_SECRET_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

_ANSWER_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


class SecurityError(ValueError):
    """Safe validation error for authentication and recovery data."""


@dataclass(frozen=True)
class SecurityQuestionAnswer:
    question: str
    answer: str


def normalize_login_method(value: str) -> str:
    value = (value or "").strip().lower()
    if value not in {"pin", "password"}:
        raise SecurityError("Choose PIN or Password.")
    return value


def validate_secret(method: str, secret: str, confirmation: str) -> str:
    method = normalize_login_method(method)
    if not isinstance(secret, str) or not isinstance(confirmation, str):
        raise SecurityError("Enter a valid PIN or password.")
    if secret != confirmation:
        raise SecurityError("The two entries do not match.")

    if method == "pin":
        if not re.fullmatch(r"\d{4,12}", secret or ""):
            raise SecurityError("Enter a PIN using 4 to 12 digits.")
        return secret

    value = secret or ""
    if len(value) < 8:
        raise SecurityError("Enter a password with at least 8 characters.")
    if len(value) > MAX_CREDENTIAL_INPUT_LENGTH:
        raise SecurityError(
            f"Password must be {MAX_CREDENTIAL_INPUT_LENGTH} characters or fewer."
        )
    return value


def hash_secret(method: str, secret: str) -> str:
    validate_secret(method, secret, secret)
    return _SECRET_HASHER.hash(secret)


def _valid_encoded_hash(stored_hash: object) -> bool:
    return (
        isinstance(stored_hash, str)
        and 1 <= len(stored_hash) <= MAX_ENCODED_HASH_LENGTH
        and stored_hash.startswith("$argon2")
    )


def verify_secret(stored_hash: str, candidate: str) -> bool:
    """Verify a login candidate while rejecting oversized/malformed input early."""
    if not _valid_encoded_hash(stored_hash):
        return False
    if (
        not isinstance(candidate, str)
        or not candidate
        or len(candidate) > MAX_CREDENTIAL_INPUT_LENGTH
    ):
        return False
    try:
        return _SECRET_HASHER.verify(stored_hash, candidate)
    except (VerificationError, InvalidHashError, TypeError, ValueError):
        return False


def normalize_security_answer(answer: str) -> str:
    if not isinstance(answer, str):
        raise SecurityError("Enter a valid security answer.")
    value = " ".join(answer.strip().split())
    if not value:
        raise SecurityError("Enter an answer for each security question.")
    if len(value) > MAX_SECURITY_ANSWER_LENGTH:
        raise SecurityError(
            f"Security answers must be {MAX_SECURITY_ANSWER_LENGTH} characters or fewer."
        )
    return value.casefold()


def validate_security_questions(
    items: Iterable[SecurityQuestionAnswer],
) -> list[SecurityQuestionAnswer]:
    cleaned: list[SecurityQuestionAnswer] = []
    seen_questions: set[str] = set()

    for item in items:
        question = " ".join((item.question or "").strip().split())
        answer = " ".join((item.answer or "").strip().split())

        if not question and not answer:
            continue
        if not question or not answer:
            raise SecurityError(
                "Each security question needs both a question and an answer."
            )
        if len(question) > 120:
            raise SecurityError("Security questions must be 120 characters or fewer.")
        if len(answer) > MAX_SECURITY_ANSWER_LENGTH:
            raise SecurityError(
                f"Security answers must be {MAX_SECURITY_ANSWER_LENGTH} characters or fewer."
            )

        key = question.casefold()
        if key in seen_questions:
            raise SecurityError("Choose two different security questions.")
        seen_questions.add(key)
        cleaned.append(SecurityQuestionAnswer(question=question, answer=answer))

    if len(cleaned) != 2:
        raise SecurityError("Configure exactly 2 security questions.")

    return cleaned


def hash_security_answer(answer: str) -> str:
    return _ANSWER_HASHER.hash(normalize_security_answer(answer))


def verify_security_answer(stored_hash: str, candidate: str) -> bool:
    """Verify recovery input with the same malformed-input limits as setup."""
    if not _valid_encoded_hash(stored_hash):
        return False
    if (
        not isinstance(candidate, str)
        or not candidate
        or len(candidate) > MAX_SECURITY_ANSWER_LENGTH
    ):
        return False
    try:
        return _ANSWER_HASHER.verify(
            stored_hash,
            normalize_security_answer(candidate),
        )
    except (VerificationError, InvalidHashError, SecurityError, TypeError, ValueError):
        return False
