"""Step 22 malformed credential/recovery input checks."""
from chitlog.core import security


class _ExplodingHasher:
    def verify(self, *_args, **_kwargs):
        raise AssertionError("Argon2 should not run for oversized malformed input")


def test_oversized_login_candidate_is_rejected_before_argon2(monkeypatch):
    monkeypatch.setattr(security, "_SECRET_HASHER", _ExplodingHasher())

    assert security.verify_secret(
        "$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        "x" * (security.MAX_CREDENTIAL_INPUT_LENGTH + 1),
    ) is False


def test_oversized_recovery_answer_is_rejected_before_argon2(monkeypatch):
    monkeypatch.setattr(security, "_ANSWER_HASHER", _ExplodingHasher())

    assert security.verify_security_answer(
        "$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        "x" * (security.MAX_SECURITY_ANSWER_LENGTH + 1),
    ) is False


def test_malformed_or_unbounded_stored_hash_is_rejected():
    assert security.verify_secret("not-an-argon2-hash", "candidate") is False
    assert security.verify_secret(
        "$argon2" + ("x" * security.MAX_ENCODED_HASH_LENGTH),
        "candidate",
    ) is False
