import ast
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _application_source() -> str:
    return (_root() / "chitlog" / "application.py").read_text(encoding="utf-8")


def _is_create_window_assignment(node: ast.AST) -> bool:
    if isinstance(node, ast.Assign):
        value = node.value
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        value = node.value
        targets = [node.target]
    else:
        return False
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    is_create = (isinstance(func, ast.Name) and func.id == "create_window") or (
        isinstance(func, ast.Attribute) and func.attr == "create_window"
    )
    return is_create and any(isinstance(t, ast.Name) and t.id == "window" for t in targets)


def test_final_startup_uses_one_shared_main_window_path():
    source = _application_source()
    tree = ast.parse(source)
    creates = [node for node in ast.walk(tree) if _is_create_window_assignment(node)]
    # Current ChitLog design intentionally converges first-run setup and normal
    # login onto one shared main-window creation path.
    assert len(creates) == 1


def test_first_run_authentication_is_refreshed_before_shared_window():
    source = _application_source()
    marker = "# STEP24_FIRST_RUN_AUTH_REFRESH_V12"
    assert marker in source
    marker_at = source.index(marker)
    window_at = source.index("window = create_window", marker_at)
    assert marker_at < window_at
    between = source[marker_at:window_at]
    assert "AuthenticationService(" in between


def test_reliable_lock_flow_is_preserved_and_connected():
    source = _application_source()
    assert "# STEP24_SESSION_LOCK_BEGIN" in source
    assert "# STEP24_SESSION_LOCK_END" in source
    assert "locked=True" in source
    assert "window.lock_requested.connect(_lock_current_session)" in source

    start = source.index("# STEP24_SESSION_LOCK_BEGIN")
    end = source.index("# STEP24_SESSION_LOCK_END", start)
    block = source[start:end]
    # The locked dialog must exist and be shown before financial content is hidden.
    assert block.index("lock_dialog = LoginDialog(") < block.index("window.hide()")
    assert block.index("lock_dialog.show()") < block.index("window.hide()")
    assert "app.processEvents()" in block
    # Failure to display the lock screen restores the main window.
    assert "except Exception:" in block
    assert "window.show()" in block
    # Closing the lock dialog exits the hidden application cleanly.
    assert "window.close()" in block
    assert "app.quit()" in block
