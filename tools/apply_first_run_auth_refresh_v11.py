from __future__ import annotations

import ast
import shutil
from pathlib import Path

MARKER = "# STEP24_FIRST_RUN_AUTH_REFRESH_V11"
LOCK_BEGIN = "# STEP24_SESSION_LOCK_BEGIN"
LOCK_END = "# STEP24_SESSION_LOCK_END"


def _named_call(node: ast.AST | None, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


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


def _segment(source: str, node: ast.AST) -> str:
    value = ast.get_source_segment(source, node)
    if not value:
        raise RuntimeError("Could not safely read the existing source expression.")
    return value


def _lock_function(tree: ast.AST) -> ast.FunctionDef:
    matches: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_lock_current_session":
            continue
        if any(_named_call(child, "LoginDialog") for child in ast.walk(node)):
            matches.append(node)
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one existing _lock_current_session() handler. "
            "Apply the v9 lock-reliability repair first."
        )
    return matches[0]


def _login_service_name(lock_function: ast.FunctionDef) -> str:
    calls = [n for n in ast.walk(lock_function) if _named_call(n, "LoginDialog")]
    call = sorted(calls, key=lambda n: (n.lineno, n.col_offset))[0]
    service_node: ast.AST | None = None
    if len(call.args) >= 2:
        service_node = call.args[1]
    else:
        for keyword in call.keywords:
            if keyword.arg == "service":
                service_node = keyword.value
                break
    if not isinstance(service_node, ast.Name):
        raise RuntimeError(
            "The lock dialog authentication service is not a simple local variable. "
            "No source was changed."
        )
    return service_node.id


def _window_assignment(scope: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.Assign | ast.AnnAssign:
    matches: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.walk(scope):
        if _scope(node, parents) is not scope:
            continue
        if isinstance(node, ast.Assign) and _named_call(node.value, "create_window"):
            if any(isinstance(t, ast.Name) and t.id == "window" for t in node.targets):
                matches.append(node)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "window"
            and _named_call(node.value, "create_window")
        ):
            matches.append(node)
    if len(matches) != 1:
        raise RuntimeError(
            "Expected the current shared startup design to have exactly one "
            f"'window = create_window(...)' statement; found {len(matches)}. No source was changed."
        )
    return matches[0]


def _authentication_assignment(
    source: str,
    scope: ast.AST,
    parents: dict[ast.AST, ast.AST],
    service_name: str,
    before_line: int,
) -> tuple[ast.Assign | ast.AnnAssign, str]:
    candidates: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.walk(scope):
        if _scope(node, parents) is not scope or node.lineno >= before_line:
            continue
        value: ast.AST | None = None
        matches_target = False
        if isinstance(node, ast.Assign):
            matches_target = any(
                isinstance(t, ast.Name) and t.id == service_name for t in node.targets
            )
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            matches_target = isinstance(node.target, ast.Name) and node.target.id == service_name
            value = node.value
        if matches_target and _named_call(value, "AuthenticationService"):
            candidates.append(node)

    if not candidates:
        raise RuntimeError(
            f"Could not find the existing AuthenticationService assignment for {service_name!r} "
            "before the main window is created. No source was changed."
        )
    node = sorted(candidates, key=lambda n: (n.lineno, n.col_offset))[-1]
    value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
    assert value is not None
    return node, _segment(source, value)


def patch_application(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        print("First-run authentication refresh v11 is already installed.")
        return False
    if LOCK_BEGIN not in source or LOCK_END not in source:
        raise RuntimeError(
            "The existing Step 24 lock wiring was not found. No source was changed."
        )

    tree = ast.parse(source)
    parents = _parents(tree)
    lock_function = _lock_function(tree)
    scope = _scope(lock_function, parents)
    service_name = _login_service_name(lock_function)
    window_node = _window_assignment(scope, parents)
    _, auth_rhs = _authentication_assignment(
        source, scope, parents, service_name, window_node.lineno
    )

    # The project has one shared create_window path. First-run setup and normal
    # login converge on that statement. The bug was therefore not missing signal
    # wiring; it was the AuthenticationService object created before first-run
    # setup and then reused after setup completed. Recreate it at the convergence
    # point so the Lock dialog always sees the newly stored PIN/password.
    lines = source.splitlines(keepends=True)
    raw = lines[window_node.lineno - 1]
    indent = raw[: len(raw) - len(raw.lstrip())]
    newline = "\r\n" if "\r\n" in source else "\n"
    insertion = (
        f"{indent}{MARKER}{newline}"
        f"{indent}# Setup can create the credential after the original auth service was built.{newline}"
        f"{indent}# Refresh it immediately before the shared main-window startup path.{newline}"
        f"{indent}{service_name} = {auth_rhs}{newline}"
    )
    lines.insert(window_node.lineno - 1, insertion)

    patched = "".join(lines)
    # Validate syntax before touching the user's source file.
    ast.parse(patched)

    backup = path.with_suffix(path.suffix + ".pre_first_run_auth_refresh_v11.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(patched, encoding="utf-8", newline="")
    print(f"Patched: {path}")
    print(f"Refreshed auth variable: {service_name}")
    print(f"Backup:  {backup}")
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
