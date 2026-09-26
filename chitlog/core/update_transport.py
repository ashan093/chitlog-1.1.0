"""Restricted HTTPS transport for ChitLog update manifests.

This is intentionally the only ChitLog runtime module approved to import
``http.client``. It performs one narrowly scoped GET to the manifest URL
already validated by UpdatePolicy.

It sends no financial data, credentials, cookies, or request body.
It never follows redirects and enforces a small response-size limit.
"""
from __future__ import annotations

from collections.abc import Callable
import http.client
from pathlib import Path
import ssl
from typing import Any
from urllib.parse import urlsplit

from chitlog.core.update_config import DEFAULT_UPDATE_POLICY, UpdatePolicy
from chitlog.core.update_installer_staging import (
    VerifiedInstallerArtifact,
    stage_installer_chunks,
)
from chitlog.core.update_manifest import UpdateManifestPayload
from chitlog.core.version import APP_NAME, APP_VERSION


class UpdateTransportError(RuntimeError):
    """Base class for safe update-manifest transport failures."""


class UpdateCheckDisabledError(UpdateTransportError):
    """Raised when no production update endpoint has been configured."""


class UpdateHTTPStatusError(UpdateTransportError):
    """Raised for redirects and non-success HTTP status codes."""


class UpdateResponseError(UpdateTransportError):
    """Raised when the server response violates update transport policy."""


class InstallerDownloadError(UpdateTransportError):
    """Base class for restricted installer-download transport failures."""


class InstallerHTTPStatusError(InstallerDownloadError):
    """Raised for installer redirects and non-success HTTP status codes."""


class InstallerResponseError(InstallerDownloadError):
    """Raised when an installer response violates download policy."""


ConnectionFactory = Callable[..., Any]
SSLContextFactory = Callable[[], ssl.SSLContext]


def _request_target(manifest_url: str) -> tuple[str, int, str]:
    parsed = urlsplit(manifest_url)

    host = parsed.hostname
    if host is None:
        raise UpdateTransportError("Update manifest URL has no host.")

    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise UpdateTransportError("Update manifest URL has an invalid port.") from exc

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    return host, port, path


def fetch_manifest_bytes(
    policy: UpdatePolicy = DEFAULT_UPDATE_POLICY,
    *,
    connection_factory: ConnectionFactory | None = None,
    ssl_context_factory: SSLContextFactory = ssl.create_default_context,
) -> bytes:
    """Fetch the configured manifest with tightly restricted HTTPS behavior."""

    if not isinstance(policy, UpdatePolicy):
        raise TypeError("policy must be an UpdatePolicy.")

    if not policy.enabled or policy.manifest_url is None:
        raise UpdateCheckDisabledError(
            "Automatic update checking is not configured."
        )

    host, port, target = _request_target(policy.manifest_url)
    context = ssl_context_factory()

    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    factory = connection_factory or http.client.HTTPSConnection
    connection = factory(
        host,
        port=port,
        timeout=policy.request_timeout_seconds,
        context=context,
    )

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": f"{APP_NAME}/{APP_VERSION} updater",
    }

    try:
        connection.request(
            "GET",
            target,
            body=None,
            headers=headers,
        )
        response = connection.getresponse()

        status = int(response.status)
        if 300 <= status <= 399:
            raise UpdateHTTPStatusError(
                "Update manifest redirects are not allowed."
            )
        if status != 200:
            raise UpdateHTTPStatusError(
                f"Update manifest request failed with HTTP status {status}."
            )

        content_encoding = (response.getheader("Content-Encoding") or "").strip()
        if content_encoding and content_encoding.lower() != "identity":
            raise UpdateResponseError(
                "Compressed update manifest responses are not accepted."
            )

        content_type = (response.getheader("Content-Type") or "").lower()
        media_type = content_type.split(";", 1)[0].strip()
        if media_type != "application/json":
            raise UpdateResponseError(
                "Update manifest response must use application/json."
            )

        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError) as exc:
                raise UpdateResponseError(
                    "Update manifest Content-Length is invalid."
                ) from exc

            if declared_length < 0:
                raise UpdateResponseError(
                    "Update manifest Content-Length is invalid."
                )
            if declared_length > policy.max_manifest_bytes:
                raise UpdateResponseError(
                    "Update manifest exceeds the configured size limit."
                )

        body = response.read(policy.max_manifest_bytes + 1)
        if len(body) > policy.max_manifest_bytes:
            raise UpdateResponseError(
                "Update manifest exceeds the configured size limit."
            )
        if not body:
            raise UpdateResponseError("Update manifest response is empty.")

        return body

    except UpdateTransportError:
        raise
    except (http.client.HTTPException, OSError, ssl.SSLError) as exc:
        raise UpdateTransportError(
            "Update manifest request failed safely."
        ) from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass

_ALLOWED_INSTALLER_MEDIA_TYPES = frozenset(
    {
        "application/octet-stream",
        "application/x-msdownload",
        "application/vnd.microsoft.portable-executable",
    }
)
_INSTALLER_READ_CHUNK_BYTES = 1024 * 1024


def _installer_request_target(installer_url: str) -> tuple[str, int, str]:
    """Revalidate a signed installer URL at the network boundary."""

    if not isinstance(installer_url, str) or not installer_url:
        raise InstallerResponseError(
            "Installer URL must be a non-empty HTTPS URL."
        )

    parsed = urlsplit(installer_url)

    if parsed.scheme.lower() != "https":
        raise InstallerResponseError("Installer URL must use HTTPS.")
    if not parsed.hostname:
        raise InstallerResponseError("Installer URL must include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise InstallerResponseError(
            "Installer URL must not contain credentials."
        )
    if parsed.fragment:
        raise InstallerResponseError(
            "Installer URL must not contain a fragment."
        )

    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise InstallerResponseError(
            "Installer URL has an invalid port."
        ) from exc

    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"

    return parsed.hostname, port, target


def _installer_response_chunks(response):
    """Yield response bytes without buffering the full installer in memory."""

    while True:
        try:
            chunk = response.read(_INSTALLER_READ_CHUNK_BYTES)
        except (http.client.HTTPException, OSError, ssl.SSLError) as exc:
            raise InstallerDownloadError(
                "Installer download failed safely while reading."
            ) from exc

        if not chunk:
            break

        if not isinstance(chunk, bytes):
            raise InstallerResponseError(
                "Installer response returned invalid binary data."
            )

        yield chunk


def download_installer_to_staging(
    payload: UpdateManifestPayload,
    destination_directory: str | Path,
    policy: UpdatePolicy = DEFAULT_UPDATE_POLICY,
    *,
    connection_factory: ConnectionFactory | None = None,
    ssl_context_factory: SSLContextFactory = ssl.create_default_context,
) -> VerifiedInstallerArtifact:
    """Download and verify a signed ChitLog installer over restricted HTTPS.

    The installer is never executed here. Network bytes are streamed directly
    into the Step 6A staging boundary, which enforces the signed byte count and
    SHA-256 before atomically finalizing the local artifact.
    """

    if not isinstance(payload, UpdateManifestPayload):
        raise TypeError("payload must be an UpdateManifestPayload.")
    if not isinstance(policy, UpdatePolicy):
        raise TypeError("policy must be an UpdatePolicy.")

    if payload.installer_size > policy.max_installer_bytes:
        raise InstallerResponseError(
            "Signed installer size exceeds the local safety limit."
        )

    host, port, target = _installer_request_target(payload.installer_url)

    context = ssl_context_factory()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    factory = connection_factory or http.client.HTTPSConnection
    connection = factory(
        host,
        port=port,
        timeout=policy.request_timeout_seconds,
        context=context,
    )

    headers = {
        "Accept": ", ".join(sorted(_ALLOWED_INSTALLER_MEDIA_TYPES)),
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": f"{APP_NAME}/{APP_VERSION} updater",
    }

    try:
        connection.request(
            "GET",
            target,
            body=None,
            headers=headers,
        )
        response = connection.getresponse()

        status = int(response.status)
        if 300 <= status <= 399:
            raise InstallerHTTPStatusError(
                "Installer download redirects are not allowed."
            )
        if status != 200:
            raise InstallerHTTPStatusError(
                f"Installer request failed with HTTP status {status}."
            )

        content_encoding = (
            response.getheader("Content-Encoding") or ""
        ).strip()
        if content_encoding and content_encoding.lower() != "identity":
            raise InstallerResponseError(
                "Compressed installer responses are not accepted."
            )

        transfer_encoding = (
            response.getheader("Transfer-Encoding") or ""
        ).strip()
        if transfer_encoding:
            raise InstallerResponseError(
                "Transfer-encoded installer responses are not accepted."
            )

        content_range = (
            response.getheader("Content-Range") or ""
        ).strip()
        if content_range:
            raise InstallerResponseError(
                "Partial installer responses are not accepted."
            )

        content_type = (
            response.getheader("Content-Type") or ""
        ).lower()
        media_type = content_type.split(";", 1)[0].strip()
        if media_type not in _ALLOWED_INSTALLER_MEDIA_TYPES:
            raise InstallerResponseError(
                "Installer response has an unsupported Content-Type."
            )

        content_length = response.getheader("Content-Length")
        if content_length is None:
            raise InstallerResponseError(
                "Installer response must include Content-Length."
            )

        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as exc:
            raise InstallerResponseError(
                "Installer Content-Length is invalid."
            ) from exc

        if declared_length <= 0:
            raise InstallerResponseError(
                "Installer Content-Length is invalid."
            )
        if declared_length != payload.installer_size:
            raise InstallerResponseError(
                "Installer Content-Length does not match the signed manifest."
            )
        if declared_length > policy.max_installer_bytes:
            raise InstallerResponseError(
                "Installer response exceeds the local safety limit."
            )

        return stage_installer_chunks(
            _installer_response_chunks(response),
            payload,
            destination_directory,
            max_installer_bytes=policy.max_installer_bytes,
        )

    except InstallerDownloadError:
        raise
    except (http.client.HTTPException, OSError, ssl.SSLError) as exc:
        raise InstallerDownloadError(
            "Installer request failed safely."
        ) from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass
