"""Collect runtime dependency license files for a ChitLog Windows release.

Run this inside the exact virtual environment used for the release build.
The script follows installed runtime requirements from ChitLog's four direct
third-party roots, copies license/notice files shipped by those distributions,
and records exact package versions. It also copies the Python license.
"""
from __future__ import annotations

import argparse
from collections import deque
from importlib import metadata
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.request

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

RUNTIME_ROOTS = (
    "PySide6",
    "sqlcipher3",
    "argon2-cffi",
    "keyring",
)


GNU_LICENSE_URLS = {
    "GPL-3.0.txt": (
        "https://www.gnu.org/licenses/gpl-3.0.txt",
        "GNU GENERAL PUBLIC LICENSE",
    ),
    "LGPL-3.0.txt": (
        "https://www.gnu.org/licenses/lgpl-3.0.txt",
        "GNU LESSER GENERAL PUBLIC LICENSE",
    ),
}

LICENSE_BASENAME = re.compile(
    r"^(license|licence|copying|copyright|notice|authors)([._-].*)?$",
    re.IGNORECASE,
)


def _installed_distribution(name: str) -> metadata.Distribution:
    try:
        return metadata.distribution(name)
    except metadata.PackageNotFoundError as error:
        raise RuntimeError(f"Required runtime distribution is not installed: {name}") from error


def _runtime_closure() -> list[metadata.Distribution]:
    env = default_environment()
    env["extra"] = ""
    queue = deque(RUNTIME_ROOTS)
    seen: set[str] = set()
    result: list[metadata.Distribution] = []

    while queue:
        requested = queue.popleft()
        key = canonicalize_name(requested)
        if key in seen:
            continue
        dist = _installed_distribution(requested)
        seen.add(canonicalize_name(dist.metadata["Name"] or requested))
        result.append(dist)

        for raw_requirement in dist.requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker is not None and not requirement.marker.evaluate(env):
                continue
            if requirement.extras:
                # ChitLog does not request optional runtime extras.
                continue
            queue.append(requirement.name)

    return sorted(
        result,
        key=lambda item: canonicalize_name(item.metadata["Name"] or ""),
    )


def _is_license_file(relative: Path) -> bool:
    if any(part.lower() in {"licenses", "license"} for part in relative.parts[:-1]):
        return True
    return bool(LICENSE_BASENAME.match(relative.name))


def _copy_distribution_licenses(
    dist: metadata.Distribution,
    output: Path,
) -> tuple[str, str, int]:
    name = dist.metadata["Name"] or "unknown"
    version = dist.version
    safe_name = canonicalize_name(name).replace("-", "_")
    target_root = output / f"{safe_name}-{version}"
    copied = 0

    for entry in dist.files or ():
        relative = Path(str(entry))
        if not _is_license_file(relative):
            continue
        source = Path(dist.locate_file(entry))
        if not source.is_file():
            continue
        destination = target_root / relative.name
        if destination.exists():
            stem, suffix = destination.stem, destination.suffix
            destination = target_root / f"{stem}-{copied + 1}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1

    license_expression = (
        dist.metadata.get("License-Expression")
        or dist.metadata.get("License")
        or "Not stated in package metadata"
    )
    return name, version, copied, license_expression


def _copy_python_license(output: Path) -> int:
    candidates = []
    for root in {Path(sys.base_prefix), Path(sys.prefix)}:
        candidates.extend(
            [
                root / "LICENSE.txt",
                root / "LICENSE",
                root / "LICENSE.rst",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            target = output / f"python-{sys.version_info.major}.{sys.version_info.minor}"
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target / candidate.name)
            return 1
    raise RuntimeError("Python license file was not found in the active interpreter installation.")


def _contains_text(output: Path, needle: str) -> bool:
    expected = needle.upper()
    for path in output.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if expected in text.upper():
            return True
    return False


def _copy_local_gnu_license_fallbacks(output: Path) -> int:
    """Copy operator-supplied GNU texts when present.

    This permits fully offline/reproducible release builds. Files may be placed
    in packaging/legal using the exact filenames in GNU_LICENSE_URLS.
    """
    legal_dir = Path(__file__).resolve().parent / "legal"
    copied = 0
    if not legal_dir.is_dir():
        return copied
    target = output / "qt-pyside6-open-source-licenses"
    for filename, (_, marker) in GNU_LICENSE_URLS.items():
        source = legal_dir / filename
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8", errors="strict")
        if marker not in text.upper() or "VERSION 3" not in text.upper():
            raise RuntimeError(f"Invalid local GNU license text: {source}")
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target / filename)
        copied += 1
    return copied


def _download_missing_gnu_license_texts(output: Path) -> int:
    """Fetch missing GPLv3/LGPLv3 texts from the official GNU HTTPS site.

    PySide6 wheel layouts do not always carry complete GNU license texts. The
    release must still contain them, so a missing text is fetched from GNU and
    validated before it is written. Any network or validation failure aborts
    the release rather than silently producing an incomplete license payload.
    """
    target = output / "qt-pyside6-open-source-licenses"
    downloaded = 0
    provenance: list[str] = []

    for filename, (url, marker) in GNU_LICENSE_URLS.items():
        if _contains_text(output, marker):
            provenance.append(f"{filename}: already supplied by installed distribution/local fallback")
            continue

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ChitLog-License-Collector/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
        except (OSError, urllib.error.URLError) as error:
            raise RuntimeError(
                f"Could not retrieve required {filename} from {url}. "
                "For an offline build, save the unmodified official GNU text "
                f"as packaging/legal/{filename} and rebuild."
            ) from error

        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError(f"Downloaded {filename} is not valid UTF-8 text.") from error

        upper = text.upper()
        if marker not in upper or "VERSION 3" not in upper:
            raise RuntimeError(
                f"Downloaded {filename} failed its license-header validation. "
                "Do not distribute this build."
            )

        target.mkdir(parents=True, exist_ok=True)
        (target / filename).write_text(text, encoding="utf-8", newline="\n")
        provenance.append(f"{filename}: {url}")
        downloaded += 1

    if provenance:
        target.mkdir(parents=True, exist_ok=True)
        (target / "SOURCE.txt").write_text(
            "ChitLog Qt/PySide6 GNU license text provenance\n"
            "The texts below are included for the LGPLv3/GPLv3 Qt for Python distribution route.\n\n"
            + "\n".join(provenance)
            + "\n",
            encoding="utf-8",
        )
    return downloaded


def _ensure_qt_gnu_license_texts(output: Path) -> None:
    _copy_local_gnu_license_fallbacks(output)
    _download_missing_gnu_license_texts(output)

    if not _contains_text(output, "GNU LESSER GENERAL PUBLIC LICENSE"):
        raise RuntimeError(
            "The release license payload still does not contain the LGPLv3 text. "
            "Do not distribute this build."
        )
    if not _contains_text(output, "GNU GENERAL PUBLIC LICENSE"):
        raise RuntimeError(
            "The release license payload still does not contain the GPLv3 text required "
            "alongside LGPLv3. Do not distribute this build."
        )


def collect(output: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("ChitLog release licenses must be collected in the Windows build environment.")

    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    distributions = _runtime_closure()
    rows: list[tuple[str, str, str, int]] = []
    for dist in distributions:
        name, version, count, license_expression = _copy_distribution_licenses(dist, output)
        rows.append((name, version, license_expression, count))

    _copy_python_license(output)

    report = [
        "ChitLog 1.1.0 runtime dependency license inventory",
        "Generated from the exact Windows release-build virtual environment.",
        "",
    ]
    for name, version, expression, count in rows:
        report.append(f"{name}=={version} | license: {expression} | copied license files: {count}")
    report.extend(
        [
            "",
            f"Python {sys.version.split()[0]} license copied from the active interpreter installation.",
            "",
            "This inventory is informational. The copied license texts govern the corresponding components.",
        ]
    )
    (output / "RUNTIME_DEPENDENCIES.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    # Qt's LGPL route requires that the release actually carries the LGPL terms.
    pyside_present = any(canonicalize_name(name) == "pyside6" for name, *_ in rows)
    if not pyside_present:
        raise RuntimeError("PySide6 was not found in the runtime dependency inventory.")
    _ensure_qt_gnu_license_texts(output)

    print(f"Collected runtime licenses for {len(rows)} Python distributions into: {output}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        collect(args.output)
    except RuntimeError as error:
        print(f"License collection failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
