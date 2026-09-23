from __future__ import annotations

import ast
import shutil
from pathlib import Path

BEGIN = "# STEP24_SESSION_LOCK_BEGIN"
END = "# STEP24_SESSION_LOCK_END"
V9 = "# STEP24_SESSION_LOCK_REPAIR_V9"
V10 = "# STEP24_FIRST_RUN_LOCK_WIRING_V10"


def _segment(source: str, node: ast.AST) -> str:
    value = ast.get_source_segment(source, node)
    if not value:
        raise RuntimeError("Could not read an existing source expression safely.")
    return value


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    result: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            result[child] = parent
    return result


def _scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            return current
    return node


def _named_call(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


def _window_assignment(node: ast.AST) -> bool:
    if isinstance(node, ast.Assign):
        if not _named_call(node.value, "create_window"):
            return False
        return any(isinstance(t, ast.Name) and t.id == "window" for t in node.targets)
    if isinstance(node, ast.AnnAssign):
        return (
            isinstance(node.target, ast.Name)
            and node.target.id == "window"
            and _named_call(node.value, "create_window")
        )
    return False


def _old_lock_function(tree: ast.AST) -> ast.FunctionDef:
    matches: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_lock_current_session":
            continue
        if any(_named_call(child, "LoginDialog") for child in ast.walk(node)):
            matches.append(node)
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one existing _lock_current_session() handler. "
            "Apply the earlier session-lock repair first."
        )
    return matches[0]


def _login_arguments(source: str, function: ast.FunctionDef) -> tuple[str, str]:
    calls = [node for node in ast.walk(function) if _named_call(node, "LoginDialog")]
    if not calls:
        raise RuntimeError("Could not find LoginDialog(...) in the existing lock handler.")
    call = sorted(calls, key=lambda item: (item.lineno, item.col_offset))[0]
    if len(call.args) >= 2:
        return _segment(source, call.args[0]), _segment(source, call.args[1])
    keywords = {item.arg: item.value for item in call.keywords if item.arg}
    assets = keywords.get("assets")
    service = keywords.get("service")
    if assets is None or service is None:
        raise RuntimeError("Could not determine LoginDialog assets/service arguments safely.")
    return _segment(source, assets), _segment(source, service)


def _find_scope_by_name(tree: ast.AST, old_scope: ast.AST) -> ast.AST:
    if isinstance(old_scope, ast.Module):
        return tree
    if not isinstance(old_scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise RuntimeError("Unsupported application scope for session lock wiring.")
    candidates = [
        n for n in ast.walk(tree)
        if isinstance(n, type(old_scope)) and getattr(n, "name", None) == old_scope.name
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"Could not uniquely relocate application scope {old_scope.name!r}.")
    return candidates[0]


def _indent_for_line(lines: list[str], lineno: int) -> str:
    line = lines[lineno - 1]
    return line[: len(line) - len(line.lstrip())]


def patch_application(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if V10 in source:
        print("First-run session-lock wiring v10 is already installed.")
        return False
    if BEGIN not in source or END not in source:
        raise RuntimeError("Existing Step 24 session-lock markers were not found.")

    tree = ast.parse(source)
    parent_map = _parents(tree)
    lock_function = _old_lock_function(tree)
    old_scope = _scope(lock_function, parent_map)
    assets_expr, service_expr = _login_arguments(source, lock_function)

    # Remove the older single-window wiring block. It was attached only to one
    # create_window() path, which is why Lock was inert immediately after setup.
    begin_at = source.index(BEGIN)
    end_at = source.index(END, begin_at) + len(END)
    line_start = source.rfind("\n", 0, begin_at) + 1
    line_end = source.find("\n", end_at)
    if line_end == -1:
        line_end = len(source)
    else:
        line_end += 1
    cleaned = source[:line_start] + source[line_end:]

    clean_tree = ast.parse(cleaned)
    clean_parents = _parents(clean_tree)
    clean_scope = _find_scope_by_name(clean_tree, old_scope)
    assignments = [
        node for node in ast.walk(clean_scope)
        if _window_assignment(node) and _scope(node, clean_parents) is clean_scope
    ]
    assignments.sort(key=lambda item: (item.lineno, item.col_offset))
    if len(assignments) < 2:
        raise RuntimeError(
            "Expected at least two main-window creation paths (first-run and normal login). "
            f"Found {len(assignments)}. No source was changed."
        )

    lines = cleaned.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in cleaned else "\n"
    if isinstance(clean_scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if not clean_scope.body:
            raise RuntimeError("Application function has no body.")
        helper_insert_line = clean_scope.body[0].lineno
        first_indent = _indent_for_line(lines, clean_scope.body[0].lineno)
    else:
        helper_insert_line = 1
        first_indent = ""
    body = first_indent + "    "
    nested = body + "    "
    deep = nested + "    "

    helper_lines = [
        f"{first_indent}{BEGIN}",
        f"{first_indent}{V9}",
        f"{first_indent}{V10}",
        f"{first_indent}def _wire_session_lock(window) -> None:",
        f"{body}# Every main-window creation path must receive the same lock handler.",
        f"{body}if getattr(window, \"_session_lock_wired\", False):",
        f"{nested}return",
        f"{body}def _lock_current_session() -> None:",
        f"{nested}# Build and display authentication before hiding financial content.",
        f"{nested}lock_dialog = None",
        f"{nested}try:",
        f"{deep}lock_dialog = LoginDialog(",
        f"{deep}    {assets_expr},",
        f"{deep}    {service_expr},",
        f"{deep}    getattr(window, \"theme_name\", \"system\"),",
        f"{deep}    locked=True,",
        f"{deep})",
        f"{deep}lock_dialog.setModal(True)",
        f"{deep}lock_dialog.show()",
        f"{deep}lock_dialog.raise_()",
        f"{deep}lock_dialog.activateWindow()",
        f"{deep}from PySide6.QtWidgets import QApplication",
        f"{deep}app = QApplication.instance()",
        f"{deep}if app is not None:",
        f"{deep}    app.processEvents()",
        f"{deep}window.hide()",
        f"{deep}accepted = bool(lock_dialog.exec())",
        f"{nested}except Exception:",
        f"{deep}# Fail safe: never leave ChitLog running invisibly.",
        f"{deep}window.show()",
        f"{deep}window.raise_()",
        f"{deep}window.activateWindow()",
        f"{deep}return",
        f"{nested}if accepted:",
        f"{deep}window.show()",
        f"{deep}window.raise_()",
        f"{deep}window.activateWindow()",
        f"{deep}return",
        f"{nested}# Closing the locked authentication surface exits ChitLog.",
        f"{nested}window.close()",
        f"{nested}from PySide6.QtWidgets import QApplication",
        f"{nested}app = QApplication.instance()",
        f"{nested}if app is not None:",
        f"{deep}app.quit()",
        f"{body}window._session_lock_handler = _lock_current_session",
        f"{body}window._session_lock_wired = True",
        f"{body}window.lock_requested.connect(_lock_current_session)",
        f"{first_indent}{END}",
        "",
    ]
    helper = newline.join(helper_lines)

    # Add the wiring call after every create_window() assignment. Insert from
    # bottom to top so original AST line numbers stay valid.
    for node in reversed(assignments):
        indent = _indent_for_line(lines, node.lineno)
        insertion = f"{indent}_wire_session_lock(window){newline}"
        lines.insert(node.end_lineno, insertion)

    # Define the helper at the enclosing function-body level, before any branch
    # can create a main window. This is essential for the first-run setup path.
    lines.insert(helper_insert_line - 1, helper)

    patched = "".join(lines)
    backup = path.with_suffix(path.suffix + ".pre_first_run_lock_wiring_v10.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(patched, encoding="utf-8", newline="")
    print(f"Patched first-run + normal-login lock wiring: {path}")
    print(f"Main-window creation paths wired: {len(assignments)}")
    print(f"Backup: {backup}")
    return True


def main() -> int:
    root = Path.cwd()
    target = root / "chitlog" / "application.py"
    if not target.is_file() or not (root / "app.py").is_file():
        raise SystemExit("Run this script from the ChitLog project root containing app.py.")
    patch_application(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
