from __future__ import annotations

import ast
import shutil
from pathlib import Path

BEGIN = "# STEP24_SESSION_LOCK_BEGIN"
END = "# STEP24_SESSION_LOCK_END"
REPAIR_MARKER = "# STEP24_SESSION_LOCK_REPAIR_V9"


def _segment(source: str, node: ast.AST) -> str:
    value = ast.get_source_segment(source, node)
    if not value:
        raise RuntimeError("Could not read an existing source expression safely.")
    return value


def _named_call(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


def _find_lock_function(tree: ast.AST) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_lock_current_session"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one _lock_current_session() function. "
            "Apply the earlier session-lock patch first."
        )
    return matches[0]


def _login_arguments(source: str, function: ast.FunctionDef) -> tuple[str, str]:
    calls = [
        node for node in ast.walk(function) if _named_call(node, "LoginDialog")
    ]
    if not calls:
        raise RuntimeError("Could not find LoginDialog(...) inside _lock_current_session().")

    call = sorted(calls, key=lambda item: (item.lineno, item.col_offset))[0]
    if len(call.args) >= 2:
        return _segment(source, call.args[0]), _segment(source, call.args[1])

    keywords = {item.arg: item.value for item in call.keywords if item.arg}
    assets_node = keywords.get("assets")
    service_node = keywords.get("service")
    if assets_node is None or service_node is None:
        raise RuntimeError("Could not determine LoginDialog assets/service arguments safely.")
    return _segment(source, assets_node), _segment(source, service_node)


def _replace_lock_block(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if REPAIR_MARKER in source:
        print("Session-lock repair v9 is already installed.")
        return False
    if BEGIN not in source or END not in source:
        raise RuntimeError(
            "The Step 24 session-lock markers were not found. "
            "Apply the session-lock feature before this repair."
        )

    tree = ast.parse(source)
    function = _find_lock_function(tree)
    assets_expr, service_expr = _login_arguments(source, function)

    begin_at = source.index(BEGIN)
    end_at = source.index(END, begin_at) + len(END)
    line_start = source.rfind("\n", 0, begin_at) + 1
    marker_line = source[line_start:begin_at]
    indent = marker_line[: len(marker_line) - len(marker_line.lstrip())]
    body = indent + "    "
    nested = body + "    "
    newline = "\r\n" if "\r\n" in source else "\n"

    block_lines = [
        f"{indent}{BEGIN}",
        f"{indent}{REPAIR_MARKER}",
        f"{indent}def _lock_current_session() -> None:",
        f"{body}# Build and display the authentication surface before hiding finance data.",
        f"{body}# This prevents a failed dialog construction from leaving ChitLog running hidden.",
        f"{body}lock_dialog = None",
        f"{body}try:",
        f"{nested}lock_dialog = LoginDialog(",
        f"{nested}    {assets_expr},",
        f"{nested}    {service_expr},",
        f"{nested}    getattr(window, \"theme_name\", \"system\"),",
        f"{nested}    locked=True,",
        f"{nested})",
        f"{nested}lock_dialog.setModal(True)",
        f"{nested}lock_dialog.show()",
        f"{nested}lock_dialog.raise_()",
        f"{nested}lock_dialog.activateWindow()",
        f"{nested}from PySide6.QtWidgets import QApplication",
        f"{nested}app = QApplication.instance()",
        f"{nested}if app is not None:",
        f"{nested}    app.processEvents()",
        f"{nested}# The lock screen is now visible; only now hide all financial content.",
        f"{nested}window.hide()",
        f"{nested}accepted = bool(lock_dialog.exec())",
        f"{body}except Exception:",
        f"{nested}# Fail safe: never strand the application as an invisible running process.",
        f"{nested}window.show()",
        f"{nested}window.raise_()",
        f"{nested}window.activateWindow()",
        f"{nested}return",
        f"{body}if accepted:",
        f"{nested}window.show()",
        f"{nested}window.raise_()",
        f"{nested}window.activateWindow()",
        f"{nested}return",
        f"{body}# Closing the locked authentication screen means exit ChitLog completely.",
        f"{body}window.close()",
        f"{body}from PySide6.QtWidgets import QApplication",
        f"{body}app = QApplication.instance()",
        f"{body}if app is not None:",
        f"{nested}app.quit()",
        "",
        f"{indent}window.lock_requested.connect(_lock_current_session)",
        f"{indent}{END}",
    ]
    replacement = newline.join(block_lines)

    backup = path.with_suffix(path.suffix + ".pre_session_lock_repair_v9.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

    patched = source[:line_start] + replacement + source[end_at:]
    path.write_text(patched, encoding="utf-8", newline="")
    print(f"Patched lock flow: {path}")
    print(f"Backup:            {backup}")
    return True


def _repair_step24_packaging_test(path: Path) -> bool:
    if not path.is_file():
        return False
    source = path.read_text(encoding="utf-8")
    old = '    assert "RequestExecutionLevel user" in script\n'
    if old not in source:
        print("Step 24 installer test already uses current mixed-scope expectations.")
        return False

    replacement = (
        '    assert "MULTIUSER_EXECUTIONLEVEL Highest" in script\n'
        '    assert "MULTIUSER_INSTALLMODE_DEFAULT_CURRENTUSER" in script\n'
        '    assert "MULTIUSER_PAGE_INSTALLMODE" in script\n'
        '    assert "$LOCALAPPDATA\\\\Programs\\\\ChitLog" in script\n'
        '    assert "$PROGRAMFILES64\\\\ChitLog" in script\n'
    )
    backup = path.with_suffix(path.suffix + ".pre_multiuser_expectation_v9.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(source.replace(old, replacement, 1), encoding="utf-8")
    print(f"Updated installer regression expectation: {path}")
    print(f"Backup:                              {backup}")
    return True


def main() -> int:
    root = Path.cwd()
    app_file = root / "chitlog" / "application.py"
    if not app_file.is_file() or not (root / "app.py").is_file():
        raise SystemExit(
            "Run this script from the ChitLog project root (the folder containing app.py)."
        )

    _replace_lock_block(app_file)
    _repair_step24_packaging_test(root / "tests" / "test_step24_packaging.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
