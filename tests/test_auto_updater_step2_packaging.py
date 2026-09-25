"""Step 2C regression tests for frozen updater cryptography support."""
from pathlib import Path

from chitlog.core.update_crypto_selftest import run_update_crypto_self_test
from chitlog.core.update_signature import TRUSTED_UPDATE_PUBLIC_KEYS


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_source_crypto_self_test_passes():
    assert run_update_crypto_self_test() == 0


def test_test_public_key_does_not_enter_production_trust_registry():
    assert dict(TRUSTED_UPDATE_PUBLIC_KEYS) == {}


def test_application_exposes_hidden_early_return_path():
    source = read("chitlog/application.py")

    assert '"--updater-crypto-self-test"' in source
    assert "if options.updater_crypto_self_test:" in source
    assert "return run_update_crypto_self_test()" in source

    branch_index = source.index("if options.updater_crypto_self_test:")
    qapp_index = source.find("QApplication", branch_index)

    # There must be a QApplication use later in normal startup, and the hidden
    # packaging self-test must branch before it.
    assert qapp_index != -1
    assert branch_index < qapp_index


def test_packaging_verifier_runs_frozen_exe_and_checks_exit_code():
    source = read("packaging/verify_updater_crypto.ps1")

    assert r"dist\ChitLog\ChitLog.exe" in source
    assert "--updater-crypto-self-test" in source
    assert "Start-Process" in source
    assert "-Wait" in source
    assert "-PassThru" in source
    assert "$Process.ExitCode -ne 0" in source


def test_packaging_selftest_contains_no_private_signing_key():
    selftest = read("chitlog/core/update_crypto_selftest.py")
    application = read("chitlog/application.py")
    verifier = read("packaging/verify_updater_crypto.ps1")
    combined = selftest + "\n" + application + "\n" + verifier

    assert "Ed25519PrivateKey" not in combined
    assert "BEGIN PRIVATE KEY" not in combined
    assert "PRIVATE_KEY" not in combined


def test_fixture_is_explicitly_separate_from_production_registry():
    source = read("chitlog/core/update_crypto_selftest.py")
    assert "TEST PUBLIC KEY" in source
    assert "production trusted update-key registry" in source
