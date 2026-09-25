"""Central ChitLog application identity and version helpers.

This module is intentionally dependency-free.  The updater foundation uses a
strict MAJOR.MINOR.PATCH version format for the stable channel.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


APP_NAME = "ChitLog"
APP_VERSION = "1.1.0"
APP_UPDATE_CHANNEL = "stable"

_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)


class VersionFormatError(ValueError):
    """Raised when a ChitLog version string is not MAJOR.MINOR.PATCH."""


@dataclass(frozen=True, order=True, slots=True)
class Version:
    """Comparable strict MAJOR.MINOR.PATCH version."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "Version":
        if not isinstance(value, str):
            raise VersionFormatError("Version must be a string.")

        match = _VERSION_RE.fullmatch(value.strip())
        if match is None:
            raise VersionFormatError(
                f"Invalid version {value!r}; expected MAJOR.MINOR.PATCH."
            )

        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def current_version() -> Version:
    """Return the running ChitLog version as a comparable Version."""

    return Version.parse(APP_VERSION)


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    """Return True only when candidate is newer than current."""

    return Version.parse(candidate) > Version.parse(current)
