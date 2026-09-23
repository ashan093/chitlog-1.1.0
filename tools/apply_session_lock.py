from __future__ import annotations

import ast
import shutil
from pathlib import Path

MARKER = "# STEP24_SESSION_LOCK_BEGIN"


def _segment(source: str, node: ast.AST) -> str:
    value = ast.get_source_segment(source, node)
    if not value:
        raise RuntimeError("Could not read an existing source expression safely.")
    return value


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            return current
    return node


def _is_named_call(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


def _login_arguments(
    source: str,
    tree: ast.AST,
    parents: dict[ast.AST, ast.AST],
    wanted_scope: ast.AST,
) -> tuple[str, str]:
    calls = [
        node
        for node in ast.walk(tree)
        if _is_named_call(node, "LoginDialog") and _scope(node, parents) is wanted_scope
    ]
    if not calls:
        raise RuntimeError(
            "Could not find the existing LoginDialog(...) startup call in the same "
            "application function that creates the main window."
        )

    for call in sorted(calls, key=lambda item: (item.lineno, item.col_offset)):
        if len(call.args) >= 2:
            return _segment(source, call.args[0]), _segment(source, call.args[1])

        keywords = {item.arg: item.value for item in call.keywords if item.arg}
        assets_node = keywords.get("assets")
        service_node = keywords.get("service")
        if assets_node is not None and service_node is not None:
            return _segment(source, assets_node), _segment(source, service_node)

    raise RuntimeError(
        "Found LoginDialog but could not determine its assets/service arguments safely."
    )


def _window_assignment(tree: ast.AST) -> ast.Assign | ast.AnnAssign:
    candidates: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not _is_named_call(node.value, "create_window"):
                continue
            if any(isinstance(target, ast.Name) and target.id == "window" for target in node.targets):
                candidates.append(node)
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name) or node.target.id != "window":
                continue
            if _is_named_call(node.value, "create_window"):
                candidates.append(node)

    if not candidates:
        raise RuntimeError("Could not find the existing 'window = create_window(...)' statement.")
    return sorted(candidates, key=lambda item: (item.lineno, item.col_offset))[-1]


def patch_application(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("Session-lock application wiring is already installed.")
        return False

    tree = ast.parse(source)
    parents = _parent_map(tree)
    window_node = _window_assignment(tree)
    window_scope = _scope(window_node, parents)
    assets_expr, service_expr = _login_arguments(
        source, tree, parents, window_scope
    )

    lines = source.splitlines(keepends=True)
    statement_line = lines[window_node.lineno - 1]
    indent = statement_line[: len(statement_line) - len(statement_line.lstrip())]
    body_indent = indent + "    "

    newline = "\r\n" if "\r\n" in source else "\n"
    block = newline.join(
        [
            "",
            f"{indent}{MARKER}",
            f"{indent}def _lock_current_session() -> None:",
            f"{body_indent}# Hide all financial information before requesting credentials.",
            f"{body_indent}window.hide()",
            f"{body_indent}lock_dialog = LoginDialog(",
            f"{body_indent}    {assets_expr},",
            f"{body_indent}    {service_expr},",
            f"{body_indent}    window.theme_name,",
            f"{body_indent}    locked=True,",
            f"{body_indent})",
            f"{body_indent}if lock_dialog.exec():",
            f"{body_indent}    window.show()",
            f"{body_indent}    window.raise_()",
            f"{body_indent}    window.activateWindow()",
            f"{body_indent}    return",
            f"{body_indent}# Closing the locked login screen exits ChitLog rather than",
            f"{body_indent}# leaving a hidden finance session running in the background.",
            f"{body_indent}window.close()",
            "",
            f"{indent}window.lock_requested.connect(_lock_current_session)",
            f"{indent}# STEP24_SESSION_LOCK_END",
            "",
        ]
    )

    insert_at = window_node.end_lineno
    lines.insert(insert_at, block)

    backup = path.with_suffix(path.suffix + ".pre_session_lock.bak")
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
