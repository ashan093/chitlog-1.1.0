"""Step 20 Settings recovery-question dropdown regression checks."""
from pathlib import Path


def test_settings_security_uses_predefined_question_dropdowns_with_custom_option():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    assert "class SecurityQuestionPicker(QWidget):" in source
    assert 'self.choice.addItem("Select a question…", "")' in source
    assert 'self.choice.addItem("Custom question…", self.CUSTOM_VALUE)' in source
    assert "COMMON_SECURITY_QUESTIONS" in source

    for question in (
        "What was the name of your first school?",
        "What was the name of your first pet?",
        "What was your childhood nickname?",
        "What is the name of a memorable place from your childhood?",
        "What was the title of a book or movie you strongly remember?",
        "What private phrase can you reliably remember?",
    ):
        assert question in source

    assert "self.question_1 = SecurityQuestionPicker()" in source
    assert "self.question_2 = SecurityQuestionPicker()" in source
    assert "Choose two different questions, or select Custom." in source


def test_question_picker_keeps_qlineedit_compatibility_api():
    project = Path(__file__).resolve().parents[1]
    source = (
        project / "chitlog/ui/pages/settings.py"
    ).read_text(encoding="utf-8")

    assert "def text(self) -> str:" in source
    assert "def setText(self, value: str) -> None:" in source
    assert "def maxLength(self) -> int:" in source
