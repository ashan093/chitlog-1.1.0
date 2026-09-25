"""Frozen-build Ed25519 self-test for the ChitLog updater.

This module contains a TEST PUBLIC KEY and a fixed signed test manifest only.
It is not part of the production trusted update-key registry and cannot
authorize a real ChitLog update.
"""
from __future__ import annotations

from chitlog.core.update_signature import parse_and_verify_manifest


_SELFTEST_KEY_ID = "chitlog-packaging-selftest-2026"

_SELFTEST_PUBLIC_KEY = bytes.fromhex(
    "0bc9dd5fb32b79f117e424d1ed87304c"
    "82f03137692a479cbdf1bf78d2d3166b"
)

_SELFTEST_MANIFEST = (
    b'{"key_id":"chitlog-packaging-selftest-2026","payload":'
    b'{"app":"ChitLog","architecture":"x64","channel":"stable",'
    b'"installer_sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
    b'"installer_size":1,'
    b'"installer_url":"https://updates.example.invalid/ChitLog-1.1.0-Setup.exe",'
    b'"mandatory":false,"minimum_supported_version":"1.1.0",'
    b'"platform":"windows","published_at":"2026-09-25T00:00:00Z",'
    b'"release_notes_url":"https://updates.example.invalid/releases/1.1.0",'
    b'"version":"1.1.0"},"schema_version":1,'
    b'"signature":"JALCFNYHNdpS19oBv7kArhaOa8QNCNudRrPWFyKyZo6VOB2gpU/PfMFSjvQ4v3NAZ0jp7x7f2HNgl5D59sScBg=="}'
)


def run_update_crypto_self_test() -> int:
    """Return 0 only when the real updater signature path works correctly."""

    try:
        payload = parse_and_verify_manifest(
            _SELFTEST_MANIFEST,
            trusted_keys={_SELFTEST_KEY_ID: _SELFTEST_PUBLIC_KEY},
        )
    except Exception:
        return 1

    if payload.app != "ChitLog":
        return 1
    if payload.version != "1.1.0":
        return 1
    if payload.installer_size != 1:
        return 1
    if payload.installer_sha256 != "0" * 64:
        return 1

    return 0
