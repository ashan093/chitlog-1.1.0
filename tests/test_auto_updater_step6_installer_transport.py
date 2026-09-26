"""Step 6B tests for restricted HTTPS installer transport."""
from __future__ import annotations

import hashlib
from pathlib import Path
import ssl

import pytest

from chitlog.core.update_config import UpdatePolicy
from chitlog.core.update_installer_staging import (
    InstallerHashError,
    InstallerSizeError,
)
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.core.update_transport import (
    InstallerDownloadError,
    InstallerHTTPStatusError,
    InstallerResponseError,
    download_installer_to_staging,
)


class FakeSSLContext:
    def __init__(self):
        self.check_hostname = False
        self.verify_mode = ssl.CERT_NONE


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        fail_on_read: Exception | None = None,
    ):
        self.status = status
        self._body = body
        self._offset = 0
        self._fail_on_read = fail_on_read
        self._headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
        }
        if headers:
            self._headers.update(headers)

    def getheader(self, name: str):
        for key, value in self._headers.items():
            if key.lower() == name.lower():
                return value
        return None

    def read(self, amount: int):
        if self._fail_on_read is not None:
            exc = self._fail_on_read
            self._fail_on_read = None
            raise exc

        if self._offset >= len(self._body):
            return b""

        end = min(self._offset + amount, len(self._body))
        chunk = self._body[self._offset:end]
        self._offset = end
        return chunk


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.host = None
        self.kwargs = None
        self.request_args = None
        self.closed = False

    def request(self, method, target, body=None, headers=None):
        self.request_args = {
            "method": method,
            "target": target,
            "body": body,
            "headers": dict(headers or {}),
        }

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def payload_for(
    data: bytes,
    *,
    installer_url: str = "https://downloads.example.test/releases/ChitLog.exe",
):
    return UpdateManifestPayload.from_dict({
        "app": "ChitLog",
        "version": "1.2.0",
        "channel": "stable",
        "platform": "windows",
        "architecture": "x64",
        "published_at": "2026-09-26T00:00:00Z",
        "minimum_supported_version": "1.0.0",
        "installer_url": installer_url,
        "installer_sha256": hashlib.sha256(data).hexdigest(),
        "installer_size": len(data),
        "release_notes_url": "https://chitlog.example.test/releases/1.2.0",
        "mandatory": False,
    })


def run_download(
    tmp_path,
    payload,
    response,
    *,
    max_installer_bytes=300 * 1024 * 1024,
):
    made = {}
    context = FakeSSLContext()

    def factory(host, **kwargs):
        connection = FakeConnection(response)
        connection.host = host
        connection.kwargs = kwargs
        made["connection"] = connection
        return connection

    artifact = download_installer_to_staging(
        payload,
        tmp_path,
        UpdatePolicy(
            manifest_url=None,
            max_installer_bytes=max_installer_bytes,
        ),
        connection_factory=factory,
        ssl_context_factory=lambda: context,
    )
    return artifact, made["connection"], context


def test_success_streams_to_step6a_and_closes_connection(tmp_path):
    data = (b"verified installer bytes" * 10000) + b"done"
    payload = payload_for(
        data,
        installer_url=(
            "https://downloads.example.test:8443/releases/"
            "ChitLog.exe?channel=stable"
        ),
    )
    response = FakeResponse(data)

    artifact, connection, context = run_download(
        tmp_path,
        payload,
        response,
    )

    assert artifact.path.name == "ChitLog-1.2.0-Setup.exe"
    assert artifact.path.read_bytes() == data
    assert artifact.sha256 == hashlib.sha256(data).hexdigest()

    assert connection.host == "downloads.example.test"
    assert connection.kwargs["port"] == 8443
    assert connection.kwargs["timeout"] == 10
    assert connection.kwargs["context"] is context

    request = connection.request_args
    assert request["method"] == "GET"
    assert request["target"] == "/releases/ChitLog.exe?channel=stable"
    assert request["body"] is None
    assert request["headers"]["Accept-Encoding"] == "identity"
    assert request["headers"]["Connection"] == "close"
    assert "Authorization" not in request["headers"]
    assert "Cookie" not in request["headers"]
    assert connection.closed is True

    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert list(tmp_path.glob("*.part")) == []


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_rejected_and_not_followed(tmp_path, status):
    data = b"installer"
    response = FakeResponse(
        data,
        status=status,
        headers={"Location": "https://other.example.test/file.exe"},
    )

    with pytest.raises(InstallerHTTPStatusError, match="redirect"):
        run_download(tmp_path, payload_for(data), response)

    assert list(tmp_path.glob("*.exe")) == []
    assert list(tmp_path.glob("*.part")) == []


@pytest.mark.parametrize("status", [201, 204, 400, 404, 500])
def test_only_http_200_is_accepted(tmp_path, status):
    data = b"installer"
    with pytest.raises(InstallerHTTPStatusError):
        run_download(
            tmp_path,
            payload_for(data),
            FakeResponse(data, status=status),
        )


@pytest.mark.parametrize(
    "content_type",
    [
        "application/octet-stream",
        "application/octet-stream; charset=binary",
        "application/x-msdownload",
        "application/vnd.microsoft.portable-executable",
    ],
)
def test_small_allowlist_of_installer_media_types(tmp_path, content_type):
    data = b"installer"
    artifact, _, _ = run_download(
        tmp_path,
        payload_for(data),
        FakeResponse(data, headers={"Content-Type": content_type}),
    )
    assert artifact.path.is_file()


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html",
        "application/json",
        "text/plain",
        "",
    ],
)
def test_unexpected_installer_content_type_is_rejected(tmp_path, content_type):
    data = b"installer"
    with pytest.raises(InstallerResponseError, match="Content-Type"):
        run_download(
            tmp_path,
            payload_for(data),
            FakeResponse(data, headers={"Content-Type": content_type}),
        )


def test_compressed_transfer_encoded_and_partial_responses_are_rejected(tmp_path):
    data = b"installer"
    payload = payload_for(data)

    with pytest.raises(InstallerResponseError, match="Compressed"):
        run_download(
            tmp_path,
            payload,
            FakeResponse(data, headers={"Content-Encoding": "gzip"}),
        )

    with pytest.raises(InstallerResponseError, match="Transfer-encoded"):
        run_download(
            tmp_path,
            payload,
            FakeResponse(data, headers={"Transfer-Encoding": "chunked"}),
        )

    with pytest.raises(InstallerResponseError, match="Partial"):
        run_download(
            tmp_path,
            payload,
            FakeResponse(data, headers={"Content-Range": "bytes 0-8/9"}),
        )


def test_content_length_is_required_valid_and_must_match_signed_size(tmp_path):
    data = b"installer"
    payload = payload_for(data)

    response = FakeResponse(data)
    del response._headers["Content-Length"]
    with pytest.raises(InstallerResponseError, match="must include"):
        run_download(tmp_path, payload, response)

    with pytest.raises(InstallerResponseError, match="invalid"):
        run_download(
            tmp_path,
            payload,
            FakeResponse(data, headers={"Content-Length": "not-a-number"}),
        )

    with pytest.raises(InstallerResponseError, match="invalid"):
        run_download(
            tmp_path,
            payload,
            FakeResponse(data, headers={"Content-Length": "0"}),
        )

    with pytest.raises(InstallerResponseError, match="signed manifest"):
        run_download(
            tmp_path,
            payload,
            FakeResponse(data, headers={"Content-Length": str(len(data) + 1)}),
        )


def test_signed_installer_above_local_limit_is_rejected_before_connect(tmp_path):
    data = b"0123456789"
    payload = payload_for(data)
    called = []

    def factory(*args, **kwargs):
        called.append(True)
        raise AssertionError("connection factory must not be called")

    with pytest.raises(InstallerResponseError, match="local safety limit"):
        download_installer_to_staging(
            payload,
            tmp_path,
            UpdatePolicy(manifest_url=None, max_installer_bytes=5),
            connection_factory=factory,
            ssl_context_factory=FakeSSLContext,
        )

    assert called == []
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_same_size_tampering_is_rejected_by_step6a_sha256(tmp_path):
    signed = b"0123456789ab"
    tampered = b"abcdefghijkl"
    assert len(signed) == len(tampered)

    with pytest.raises(InstallerHashError):
        run_download(
            tmp_path,
            payload_for(signed),
            FakeResponse(tampered),
        )

    assert list(tmp_path.glob("*.exe")) == []
    assert list(tmp_path.glob("*.part")) == []


def test_short_response_is_rejected_by_signed_size_boundary(tmp_path):
    signed = b"0123456789"
    received = b"0123"
    response = FakeResponse(
        received,
        headers={"Content-Length": str(len(signed))},
    )

    with pytest.raises(InstallerSizeError):
        run_download(
            tmp_path,
            payload_for(signed),
            response,
        )

    assert list(tmp_path.glob("*.part")) == []


def test_read_failure_is_wrapped_safely_and_part_file_is_removed(tmp_path):
    data = b"installer"
    response = FakeResponse(
        data,
        fail_on_read=OSError("simulated network interruption"),
    )

    with pytest.raises(InstallerDownloadError, match="reading"):
        run_download(
            tmp_path,
            payload_for(data),
            response,
        )

    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("*.exe")) == []


def test_connection_failure_is_wrapped_safely(tmp_path):
    data = b"installer"

    class BrokenConnection:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def request(self, *args, **kwargs):
            raise OSError("simulated connection failure")

        def close(self):
            self.closed = True

    with pytest.raises(InstallerDownloadError, match="failed safely"):
        download_installer_to_staging(
            payload_for(data),
            tmp_path,
            UpdatePolicy(manifest_url=None),
            connection_factory=BrokenConnection,
            ssl_context_factory=FakeSSLContext,
        )


def test_transport_revalidates_installer_url_even_for_fabricated_payload(tmp_path):
    from dataclasses import replace

    data = b"installer"
    unsafe = replace(
        payload_for(data),
        installer_url="http://downloads.example.test/ChitLog.exe",
    )

    with pytest.raises(InstallerResponseError, match="HTTPS"):
        download_installer_to_staging(
            unsafe,
            tmp_path,
            UpdatePolicy(manifest_url=None),
            connection_factory=lambda *a, **k: None,
            ssl_context_factory=FakeSSLContext,
        )


def test_installer_transport_does_not_execute_or_use_other_network_clients():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/core/update_transport.py"
    ).read_text(encoding="utf-8")

    assert "download_installer_to_staging" in source
    assert "stage_installer_chunks(" in source
    assert "http.client.HTTPSConnection" in source

    for forbidden in (
        "requests",
        "httpx",
        "urllib.request",
        "PySide6.QtNetwork",
        "subprocess",
        "Popen",
        "os.startfile",
        "ShellExecute",
        "QProcess",
    ):
        assert forbidden not in source
