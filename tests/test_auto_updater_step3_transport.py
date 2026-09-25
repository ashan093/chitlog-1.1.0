"""Step 3B tests for the restricted ChitLog HTTPS update transport."""
from __future__ import annotations

import ast
import ssl
from pathlib import Path

import pytest

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_transport import (
    UpdateCheckDisabledError,
    UpdateHTTPStatusError,
    UpdateResponseError,
    UpdateTransportError,
    fetch_manifest_bytes,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(
        self,
        body: bytes = b'{"ok":true}',
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self._body = body
        self._headers = {
            key.lower(): value for key, value in (headers or {}).items()
        }

    def getheader(self, name: str):
        return self._headers.get(name.lower())

    def read(self, amount: int):
        return self._body[:amount]


class FakeConnection:
    instances = []
    response = FakeResponse(headers={"Content-Type": "application/json"})
    request_error = None

    def __init__(self, host, *, port, timeout, context):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.request_args = None
        self.closed = False
        type(self).instances.append(self)

    def request(self, method, target, *, body, headers):
        self.request_args = (method, target, body, headers)
        if type(self).request_error is not None:
            raise type(self).request_error

    def getresponse(self):
        return type(self).response

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_connection():
    FakeConnection.instances = []
    FakeConnection.response = FakeResponse(
        headers={"Content-Type": "application/json"}
    )
    FakeConnection.request_error = None
    yield


def policy(**overrides):
    values = {
        "manifest_url": "https://updates.example.test/api/updates/windows/stable",
        "request_timeout_seconds": 7,
        "max_manifest_bytes": 1024,
    }
    values.update(overrides)
    return UpdatePolicy(**values)


def test_disabled_policy_performs_no_connection_attempt():
    def forbidden_factory(*args, **kwargs):
        raise AssertionError("network factory must not be called")

    with pytest.raises(UpdateCheckDisabledError):
        fetch_manifest_bytes(
            UpdatePolicy(manifest_url=None),
            connection_factory=forbidden_factory,
        )


def test_single_https_get_has_no_body_credentials_cookies_or_private_data():
    body = fetch_manifest_bytes(
        policy(),
        connection_factory=FakeConnection,
    )

    assert body == b'{"ok":true}'
    assert len(FakeConnection.instances) == 1

    connection = FakeConnection.instances[0]
    assert connection.host == "updates.example.test"
    assert connection.port == 443
    assert connection.timeout == 7
    assert connection.context.verify_mode == ssl.CERT_REQUIRED
    assert connection.context.check_hostname is True

    method, target, request_body, headers = connection.request_args
    assert method == "GET"
    assert target == "/api/updates/windows/stable"
    assert request_body is None
    assert headers["Accept"] == "application/json"
    assert headers["Accept-Encoding"] == "identity"
    assert headers["Connection"] == "close"
    assert "Cookie" not in headers
    assert "Authorization" not in headers

    rendered = repr(headers).lower()
    for forbidden in (
        "transaction",
        "income",
        "expense",
        "worker",
        "liability",
        "budget",
        "password",
        "pin",
    ):
        assert forbidden not in rendered

    assert connection.closed is True


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_rejected_and_never_followed(status):
    FakeConnection.response = FakeResponse(
        status=status,
        headers={
            "Content-Type": "application/json",
            "Location": "https://evil.example.test/manifest.json",
        },
    )

    with pytest.raises(UpdateHTTPStatusError, match="redirect"):
        fetch_manifest_bytes(
            policy(),
            connection_factory=FakeConnection,
        )

    assert len(FakeConnection.instances) == 1
    assert FakeConnection.instances[0].closed is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_non_200_status_is_rejected(status):
    FakeConnection.response = FakeResponse(
        status=status,
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(UpdateHTTPStatusError, match=str(status)):
        fetch_manifest_bytes(
            policy(),
            connection_factory=FakeConnection,
        )


@pytest.mark.parametrize(
    "content_type",
    ["", "text/plain", "text/html", "application/octet-stream"],
)
def test_non_json_content_type_is_rejected(content_type):
    FakeConnection.response = FakeResponse(
        headers={"Content-Type": content_type},
    )
    with pytest.raises(UpdateResponseError, match="application/json"):
        fetch_manifest_bytes(
            policy(),
            connection_factory=FakeConnection,
        )


def test_json_content_type_with_charset_is_accepted():
    FakeConnection.response = FakeResponse(
        body=b'{"signed":"manifest"}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert fetch_manifest_bytes(
        policy(),
        connection_factory=FakeConnection,
    ) == b'{"signed":"manifest"}'


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate"])
def test_compressed_manifest_is_rejected(encoding):
    FakeConnection.response = FakeResponse(
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": encoding,
        },
    )
    with pytest.raises(UpdateResponseError, match="Compressed"):
        fetch_manifest_bytes(
            policy(),
            connection_factory=FakeConnection,
        )


def test_declared_oversized_manifest_is_rejected_before_read():
    FakeConnection.response = FakeResponse(
        body=b"x",
        headers={
            "Content-Type": "application/json",
            "Content-Length": "1025",
        },
    )
    with pytest.raises(UpdateResponseError, match="size"):
        fetch_manifest_bytes(
            policy(max_manifest_bytes=1024),
            connection_factory=FakeConnection,
        )


@pytest.mark.parametrize("content_length", ["abc", "-1"])
def test_invalid_content_length_is_rejected(content_length):
    FakeConnection.response = FakeResponse(
        headers={
            "Content-Type": "application/json",
            "Content-Length": content_length,
        },
    )
    with pytest.raises(UpdateResponseError, match="Content-Length"):
        fetch_manifest_bytes(
            policy(),
            connection_factory=FakeConnection,
        )


def test_streamed_body_cannot_bypass_size_limit():
    FakeConnection.response = FakeResponse(
        body=b"x" * 1025,
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(UpdateResponseError, match="size"):
        fetch_manifest_bytes(
            policy(max_manifest_bytes=1024),
            connection_factory=FakeConnection,
        )


def test_empty_body_is_rejected():
    FakeConnection.response = FakeResponse(
        body=b"",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(UpdateResponseError, match="empty"):
        fetch_manifest_bytes(
            policy(),
            connection_factory=FakeConnection,
        )


def test_transport_failure_is_wrapped_and_connection_is_closed():
    FakeConnection.request_error = OSError("offline")

    with pytest.raises(UpdateTransportError, match="failed safely"):
        fetch_manifest_bytes(
            policy(),
            connection_factory=FakeConnection,
        )

    assert FakeConnection.instances[0].closed is True


def test_query_is_preserved_only_from_configured_manifest_url():
    result = fetch_manifest_bytes(
        policy(
            manifest_url=(
                "https://updates.example.test/api/updates?channel=stable"
            )
        ),
        connection_factory=FakeConnection,
    )
    assert result == b'{"ok":true}'
    assert FakeConnection.instances[0].request_args[1] == (
        "/api/updates?channel=stable"
    )


def test_http_client_import_is_confined_to_the_approved_transport_file():
    offenders = []
    approved = "chitlog/core/update_transport.py"

    for path in (ROOT / "chitlog").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported = False
            if isinstance(node, ast.Import):
                imported = any(
                    alias.name == "http.client" for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                imported = node.module == "http.client"

            if imported and relative != approved:
                offenders.append(relative)

    assert offenders == []


def test_transport_does_not_import_broad_external_network_clients():
    source = (ROOT / "chitlog/core/update_transport.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "import socket",
        "from socket",
        "urllib.request",
        "PySide6.QtNetwork",
    )
    for needle in forbidden:
        assert needle not in source
