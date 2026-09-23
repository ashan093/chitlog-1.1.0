"""Step 22 salary-slip atomic file handling."""
from pathlib import Path

import pytest

from chitlog.services.salary_slip_service import SalarySlipError, SalarySlipPdfService


class Workers:
    def get_worker(self, worker_id):
        return object() if worker_id == 1 else None


class Payroll:
    def summary_for_worker(self, worker_id, month):
        return object()


def test_failed_pdf_render_does_not_overwrite_previous_valid_file(tmp_path, monkeypatch):
    output = tmp_path / "salary-slip.pdf"
    previous = b"%PDF-existing-valid-file"
    output.write_bytes(previous)

    service = SalarySlipPdfService(Workers(), Payroll(), "LKR", "Rs")

    def fail_render(*_args, **_kwargs):
        raise SalarySlipError("simulated render failure")

    monkeypatch.setattr(service, "_render_pdf", fail_render)

    with pytest.raises(SalarySlipError):
        service.generate(output, [1], "2026-09-01")

    assert output.read_bytes() == previous
    assert list(tmp_path.glob(".*.part")) == []


def test_pdf_output_rejects_symbolic_link_when_supported(tmp_path):
    target = tmp_path / "target.pdf"
    target.write_bytes(b"existing")
    link = tmp_path / "linked.pdf"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are not available in this test environment")

    service = SalarySlipPdfService(Workers(), Payroll(), "LKR", "Rs")
    with pytest.raises(SalarySlipError, match="symbolic link"):
        service.generate(link, [1], "2026-09-01")
