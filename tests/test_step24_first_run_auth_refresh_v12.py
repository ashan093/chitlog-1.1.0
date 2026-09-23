import importlib.util
from pathlib import Path


def load_patcher():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "apply_first_run_auth_refresh_v12.py"
    spec = importlib.util.spec_from_file_location("lock_refresh_v12", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_patcher_handles_python314_arguments_nodes(tmp_path):
    mod = load_patcher()
    src = '''\nfrom x import AuthenticationService, LoginDialog, create_window\n\ndef run():\n    service = AuthenticationService("repo")\n    def _lock_current_session():\n        dlg = LoginDialog(None, service)\n        return dlg\n    # STEP24_SESSION_LOCK_BEGIN\n    marker = True\n    # STEP24_SESSION_LOCK_END\n    window = create_window(service=service)\n    return window\n'''.lstrip()
    p = tmp_path / "application.py"
    p.write_text(src, encoding="utf-8")
    assert mod.patch_application(p) is True
    out = p.read_text(encoding="utf-8")
    assert mod.MARKER in out
    assert out.count('service = AuthenticationService("repo")') == 2


def test_v12_source_filters_assignment_before_lineno_access():
    root = Path(__file__).resolve().parents[1]
    text = (root / "tools" / "apply_first_run_auth_refresh_v12.py").read_text(encoding="utf-8")
    assert "if not isinstance(node, (ast.Assign, ast.AnnAssign))" in text
    assert "if node.lineno >= before_line" in text
