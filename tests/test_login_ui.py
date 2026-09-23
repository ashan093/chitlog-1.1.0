"""Small offscreen regressions for login/recovery UI behavior."""
import os
from pathlib import Path
import subprocess
import sys


def run_offscreen(code: str):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_login_dialog_retries_inline_without_lockout_label():
    code = r'''
from PySide6.QtWidgets import QApplication, QDialog, QLabel
from chitlog.ui.login_dialog import LoginDialog
from chitlog.core.config import ASSETS

class Service:
    def __init__(self): self.calls = 0
    def login_method(self): return "pin"
    def verify_login(self, value):
        self.calls += 1
        return value == "2468"

app = QApplication([])
service = Service()
w = LoginDialog(ASSETS, service, "dark")
w.show()
app.processEvents()
assert not w.windowIcon().isNull()
assert not any("does not lock" in label.text().lower() for label in w.findChildren(QLabel))
for _ in range(12):
    w.secret.edit.setText("0000")
    w._login()
    assert w.result() != QDialog.DialogCode.Accepted
    assert w.error.text()
assert service.calls == 12
w.secret.edit.setText("2468")
w._login()
assert w.result() == QDialog.DialogCode.Accepted
assert service.calls == 13
'''
    run_offscreen(code)


def test_recovery_wrong_answer_keeps_stable_error_geometry():
    code = r'''
from PySide6.QtWidgets import QApplication
from chitlog.ui.login_dialog import RecoveryDialog

class Question:
    def __init__(self, p, q): self.position=p; self.question=q
class Service:
    def login_method(self): return "pin"
    def recovery_questions(self): return [Question(1,"Question one?"), Question(2,"Question two?")]
    def verify_recovery_answers(self, answers): return False

app = QApplication([])
w = RecoveryDialog(Service(), "dark")
w.show()
app.processEvents()
before = [field.height() for field in w.answer_inputs]
for field, text in zip(w.answer_inputs, ["wrong", "also wrong"]): field.edit.setText(text)
w._verify_answers()
app.processEvents()
after = [field.height() for field in w.answer_inputs]
assert w.recovery_error.text()
assert w.recovery_error.minimumHeight() >= 40
assert min(after) >= min(before)
assert all(field.edit.height() >= 30 for field in w.answer_inputs)
w.close()
'''
    run_offscreen(code)


def test_recovery_can_choose_new_login_method_and_login_updates():
    code = r'''
from PySide6.QtWidgets import QApplication
from chitlog.ui.login_dialog import LoginDialog, RecoveryDialog
from chitlog.core.config import ASSETS

class Question:
    def __init__(self,p,q): self.position=p; self.question=q
class Service:
    def __init__(self): self.method="pin"; self.saved=None
    def login_method(self): return self.method
    def verify_login(self, value): return False
    def recovery_questions(self): return [Question(1,"Q1?"),Question(2,"Q2?")]
    def verify_recovery_answers(self, answers): return True
    def reset_credentials(self, method, secret, confirmation):
        assert secret == confirmation
        self.method=method; self.saved=(method,secret)

app = QApplication([])
service=Service()
r=RecoveryDialog(service,"dark")
r.reset_password.setChecked(True)
r.new_secret.edit.setText("password123")
r.confirm_secret.edit.setText("password123")
method=[]
r.secret_reset.connect(method.append)
r._reset_credentials()
assert method == ["password"]
assert service.saved == ("password","password123")

w=LoginDialog(ASSETS,service,"dark")
w._recovery_completed("password")
assert w.method == "password"
assert "Password" in w.prompt_label.text()
assert "Password" in w.forgot_button.text()
w.close()
'''
    run_offscreen(code)
