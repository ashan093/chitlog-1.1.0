"""Step 2B1: cryptography runtime dependency smoke tests."""
from cryptography import __version__ as cryptography_version
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)


def test_cryptography_version_is_expected():
    assert cryptography_version == "50.0.1"


def test_ed25519_sign_and_verify_round_trip():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    message = b"ChitLog updater signature smoke test"

    signature = private_key.sign(message)
    assert len(signature) == 64
    public_key.verify(signature, message)


def test_ed25519_rejects_tampered_message():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    signature = private_key.sign(b"original")

    try:
        public_key.verify(signature, b"tampered")
    except InvalidSignature:
        pass
    else:
        raise AssertionError("Tampered Ed25519 message was accepted.")
