"""Static security guardrails for ChitLog V1.

Run manually before packaging:
    python -m chitlog.core.security_audit

The audit never opens the user's database and never reads user financial data.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re
import sys


FORBIDDEN_IMPORTS = frozenset(
    {
        "pickle",
        "marshal",
        "shelve",
        "requests",
        "httpx",
        "socket",
        "urllib.request",
        "PySide6.QtNetwork",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
    }
)

SUSPICIOUS_SECRET_NAMES = frozenset(
    {
        "api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "secret_key",
        "password",
        "pin",
        "token",
    }
)

DEVELOPER_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\[^\\]+", re.IGNORECASE),
    re.compile(r"/home/[^/]+/"),
)

FORBIDDEN_RUNTIME_FILES = frozenset(
    {
        "google_drive_token_store.py",
        "google_drive_backup_service.py",
        "google_drive_backup.py",
    }
)


@dataclass(frozen=True, order=True)
class AuditIssue:
    category: str
    path: str
    line: int
    detail: str


def _module_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return None
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _SecurityVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str):
        self.relative_path = relative_path
        self.issues: list[AuditIssue] = []

    def issue(self, node: ast.AST, category: str, detail: str) -> None:
        self.issues.append(
            AuditIssue(
                category=category,
                path=self.relative_path,
                line=int(getattr(node, "lineno", 0) or 0),
                detail=detail,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            if name in FORBIDDEN_IMPORTS:
                self.issue(
                    node,
                    "network_or_unsafe_import",
                    f"forbidden runtime import: {name}",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module in FORBIDDEN_IMPORTS:
            self.issue(
                node,
                "network_or_unsafe_import",
                f"forbidden runtime import: {module}",
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
            self.issue(
                node,
                "script_execution",
                f"built-in {node.func.id}() is not allowed",
            )

        if isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                isinstance(owner, ast.Name)
                and owner.id == "os"
                and node.func.attr in {"system", "popen"}
            ):
                self.issue(
                    node,
                    "script_execution",
                    f"os.{node.func.attr}() is not allowed",
                )

            if node.func.attr == "set_trace_callback":
                self.issue(
                    node,
                    "sql_logging",
                    "SQLite trace callbacks can expose private financial values",
                )

            if (
                isinstance(owner, ast.Name)
                and owner.id == "subprocess"
                and node.func.attr in {"run", "call", "check_call", "check_output", "Popen"}
            ):
                for keyword in node.keywords:
                    if (
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        self.issue(
                            node,
                            "script_execution",
                            "subprocess shell=True is not allowed",
                        )

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _literal_string(node.value)
        if value:
            for name in _assigned_names(node):
                if name.casefold() in SUSPICIOUS_SECRET_NAMES:
                    self.issue(
                        node,
                        "hardcoded_secret",
                        f"non-empty literal assigned to sensitive name {name!r}",
                    )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        value = _literal_string(node.value)
        if value:
            for name in _assigned_names(node):
                if name.casefold() in SUSPICIOUS_SECRET_NAMES:
                    self.issue(
                        node,
                        "hardcoded_secret",
                        f"non-empty literal assigned to sensitive name {name!r}",
                    )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            for pattern in DEVELOPER_PATH_PATTERNS:
                if pattern.search(node.value):
                    self.issue(
                        node,
                        "developer_path",
                        "hard-coded developer user path found",
                    )
                    break
        self.generic_visit(node)


def audit_project(project_root: str | Path | None = None) -> list[AuditIssue]:
    root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    package = root / "chitlog"
    issues: list[AuditIssue] = []

    if not package.is_dir():
        return [
            AuditIssue(
                "project_layout",
                "chitlog",
                0,
                "ChitLog package folder was not found",
            )
        ]

    for forbidden_name in FORBIDDEN_RUNTIME_FILES:
        matches = list(package.rglob(forbidden_name))
        for match in matches:
            issues.append(
                AuditIssue(
                    "deferred_feature",
                    str(match.relative_to(root)),
                    0,
                    "Google Drive/OAuth V2 code must not be packaged in V1",
                )
            )

    for path in sorted(package.rglob("*.py")):
        if path.name == "security_audit.py":
            continue
        relative = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
        except (OSError, UnicodeError, SyntaxError) as error:
            issues.append(
                AuditIssue(
                    "source_read",
                    relative,
                    int(getattr(error, "lineno", 0) or 0),
                    "source could not be parsed safely",
                )
            )
            continue

        visitor = _SecurityVisitor(relative)
        visitor.visit(tree)
        issues.extend(visitor.issues)

    requirements = root / "requirements.txt"
    if requirements.exists():
        try:
            lines = {
                line.split("==", 1)[0]
                .split(";", 1)[0]
                .strip()
                .lower()
                for line in requirements.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            }
        except OSError:
            issues.append(
                AuditIssue(
                    "requirements",
                    "requirements.txt",
                    0,
                    "requirements file could not be read",
                )
            )
        else:
            for forbidden in (
                "requests",
                "httpx",
                "google-api-python-client",
                "google-auth-oauthlib",
            ):
                if forbidden in lines:
                    issues.append(
                        AuditIssue(
                            "network_dependency",
                            "requirements.txt",
                            0,
                            f"unexpected V1 network dependency: {forbidden}",
                        )
                    )

    return sorted(set(issues))


def main() -> int:
    issues = audit_project()
    if not issues:
        print("CHITLOG SECURITY REVIEW: PASS")
        print(
            "No forbidden script execution, broad network client, embedded web "
            "engine, hard-coded credential literal, developer path, SQL trace, "
            "or deferred Google Drive module was detected."
        )
        return 0

    print("CHITLOG SECURITY REVIEW: FAIL")
    for issue in issues:
        location = f"{issue.path}:{issue.line}" if issue.line else issue.path
        print(f"- [{issue.category}] {location} — {issue.detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
