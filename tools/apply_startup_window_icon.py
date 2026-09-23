from __future__ import annotations

import ast
import shutil
from pathlib import Path

MARKER = "# STEP24_GLOBAL_WINDOW_ICON_HELPER_BEGIN"


def _segment(source: str, node: ast.AST) -> str:
    value = ast.get_source_segment(source, node)
    if not value:
        raise RuntimeError("Could not read the existing assets expression safely.")
    return value


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _statement(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.stmt:
    current = node
    while not isinstance(current, ast.stmt):
        current = parents[current]
    return current


def _named_call(node: ast.AST, names: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in names
    if isinstance(func, ast.Attribute):
        return func.attr in names
    return False


def _assets_expression(source: str, call: ast.Call) -> str:
    if call.args:
        return _segment(source, call.args[0])
    for keyword in call.keywords:
        if keyword.arg == "assets":
            return _segment(source, keyword.value)
    raise RuntimeError("Could not determine the assets argument for a startup dialog.")


def patch_application(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Global ChitLog startup icon wiring is already installed.")
        return False

    tree = ast.parse(source)
    parents = _parent_map(tree)
    lines = source.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in source else "\n"

    # Find setup/login construction sites. The session-lock LoginDialog is also
    # included deliberately; calling the helper again is harmless and keeps all
    # authentication surfaces consistent.
    sites: dict[int, tuple[ast.stmt, str]] = {}
    for node in ast.walk(tree):
        if not _named_call(node, {"SetupWizard", "LoginDialog"}):
            continue
        assert isinstance(node, ast.Call)
        stmt = _statement(node, parents)
        sites.setdefault(stmt.lineno, (stmt, _assets_expression(source, node)))

    if not sites:
        raise RuntimeError("Could not find SetupWizard(...) or LoginDialog(...) in chitlog/application.py.")

    # Insert a tiny helper after the import block, before application functions
    # are defined/executed.
    import_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_end = max(import_end, node.end_lineno or node.lineno)
        elif isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            # Module docstring may precede imports.
            continue
        else:
            if import_end:
                break

    helper = newline.join(
        [
            "",
            MARKER,
            "def _apply_chitlog_window_icon(assets) -> None:",
            "    # QApplication-level icon becomes the default for every top-level",
            "    # window, including first-run PIN/password setup and login/lock.",
            "    from PySide6.QtGui import QIcon",
            "    from PySide6.QtWidgets import QApplication",
            "",
            "    app = QApplication.instance()",
            "    icon_path = assets / \"chit.png\"",
            "    if app is not None and icon_path.is_file():",
            "        app.setWindowIcon(QIcon(str(icon_path)))",
            "# STEP24_GLOBAL_WINDOW_ICON_HELPER_END",
            "",
        ]
    )

    modifications: list[tuple[int, str]] = [(import_end, helper)]
    for lineno, (stmt, assets_expr) in sites.items():
        raw = lines[stmt.lineno - 1]
        indent = raw[: len(raw) - len(raw.lstrip())]
        block = (
            f"{indent}_apply_chitlog_window_icon({assets_expr}){newline}"
        )
        modifications.append((stmt.lineno - 1, block))

    for index, text in sorted(modifications, key=lambda item: item[0], reverse=True):
        lines.insert(index, text)

    backup = path.with_suffix(path.suffix + ".pre_global_window_icon.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text("".join(lines), encoding="utf-8", newline="")
    print(f"Patched: {path}")
    print(f"Backup:  {backup}")
    return True


def main() -> int:
    project = Path.cwd()
    target = project / "chitlog" / "application.py"
    if not target.is_file():
        raise SystemExit(
            "Run this script from the ChitLog project root (the folder containing app.py)."
        )
    patch_application(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
