"""Step 7B tests for the standalone updater process skeleton."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from chitlog.core.update_process_wait import (
    UpdateProcessTimeoutError,
    UpdateProcessWaitError,
    wait_for_process_exit,
)
from chitlog.updater import (
    EXIT_HANDOFF_REJECTED,
    EXIT_PARENT_WAIT_FAILED,
    EXIT_READY_NO_EXECUTION,
    UpdateHandoffChangedError,
    build_argument_parser,
    main,
    prepare_standalone_update,
)


def fake_verified(*, pid=12345, version="1.2.0", marker="same"):
    handoff = SimpleNamespace(
        parent_pid=pid,
        marker=marker,
    )
    payload = SimpleNamespace(version=version)
    return SimpleNamespace(
        handoff=handoff,
        payload=payload,
    )


def test_prepare_verifies_before_and_after_wait():
    calls = []
    before = fake_verified()
    after = fake_verified()

    def verifier(path):
        calls.append(("verify", Path(path)))
        return before if len(calls) == 1 else after

    def waiter(pid):
        calls.append(("wait", pid))

    result = prepare_standalone_update(
        Path("handoff.json"),
        verifier=verifier,
        waiter=waiter,
    )

    assert result is after
    assert calls == [
        ("verify", Path("handoff.json")),
        ("wait", 12345),
        ("verify", Path("handoff.json")),
    ]


def test_handoff_change_during_wait_is_rejected():
    before = fake_verified(marker="before")
    after = fake_verified(marker="after")
    values = iter([before, after])

    with pytest.raises(UpdateHandoffChangedError, match="changed"):
        prepare_standalone_update(
            Path("handoff.json"),
            verifier=lambda path: next(values),
            waiter=lambda pid: None,
        )


def test_payload_change_during_wait_is_rejected():
    before = fake_verified(version="1.2.0")
    after = fake_verified(version="1.3.0")
    after.handoff = before.handoff
    values = iter([before, after])

    with pytest.raises(UpdateHandoffChangedError, match="payload"):
        prepare_standalone_update(
            Path("handoff.json"),
            verifier=lambda path: next(values),
            waiter=lambda pid: None,
        )


def test_wait_failure_stops_before_second_verification():
    calls = []

    def verifier(path):
        calls.append("verify")
        return fake_verified()

    def waiter(pid):
        calls.append("wait")
        raise UpdateProcessWaitError("simulated")

    with pytest.raises(UpdateProcessWaitError):
        prepare_standalone_update(
            Path("handoff.json"),
            verifier=verifier,
            waiter=waiter,
        )

    assert calls == ["verify", "wait"]


@pytest.mark.parametrize("pid", [0, -1, True, 0x100000000])
def test_process_wait_rejects_invalid_pid(pid):
    with pytest.raises(ValueError, match="parent_pid"):
        wait_for_process_exit(pid, timeout_seconds=0.05)


@pytest.mark.parametrize("timeout", [0, -1, 3600.1])
def test_process_wait_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        wait_for_process_exit(99999999, timeout_seconds=timeout)


def test_process_wait_rejects_self_pid():
    with pytest.raises(UpdateProcessWaitError, match="own process"):
        wait_for_process_exit(os.getpid(), timeout_seconds=0.05)


def test_nonexistent_process_returns_without_termination_or_launch():
    try:
        wait_for_process_exit(0xFFFFFFFE, timeout_seconds=0.05)
    except UpdateProcessTimeoutError:
        pytest.skip("Selected high PID unexpectedly exists on this host.")


def test_real_process_wait_observes_exit_without_terminating():
    # -S skips environment/site startup hooks so this is a deterministic,
    # short-lived child in both CI and the Windows development environment.
    child = subprocess.Popen(
        [
            sys.executable,
            "-S",
            "-c",
            "import time; time.sleep(0.15)",
        ]
    )
    try:
        started = time.monotonic()
        wait_for_process_exit(child.pid, timeout_seconds=3.0)
        elapsed = time.monotonic() - started
        child.wait(timeout=3)

        assert child.returncode == 0
        assert elapsed >= 0.05
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)


def test_argument_parser_accepts_only_handoff_option():
    parser = build_argument_parser()
    args = parser.parse_args(["--handoff", r"C:\Temp\handoff.json"])
    assert args.handoff == r"C:\Temp\handoff.json"

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--handoff",
                r"C:\Temp\handoff.json",
                "--installer",
                r"C:\Temp\evil.exe",
            ]
        )


def test_main_rejects_relative_handoff_before_verification(monkeypatch, capsys):
    import chitlog.updater as updater

    called = []
    monkeypatch.setattr(
        updater,
        "prepare_standalone_update",
        lambda path: called.append(path),
    )

    code = main(["--handoff", "relative.json"])
    captured = capsys.readouterr()

    assert code == EXIT_HANDOFF_REJECTED
    assert called == []
    assert "absolute path" in captured.err


def test_main_maps_handoff_failure_to_fail_closed_exit(monkeypatch, tmp_path, capsys):
    import chitlog.updater as updater
    from chitlog.core.update_handoff import UpdateHandoffError

    handoff = (tmp_path / "handoff.json").resolve()
    monkeypatch.setattr(
        updater,
        "prepare_standalone_update",
        lambda path: (_ for _ in ()).throw(UpdateHandoffError("secret")),
    )

    code = main(["--handoff", str(handoff)])
    captured = capsys.readouterr()

    assert code == EXIT_HANDOFF_REJECTED
    assert "Nothing was installed" in captured.err
    assert "secret" not in captured.err


def test_main_maps_wait_failure_to_fail_closed_exit(monkeypatch, tmp_path, capsys):
    import chitlog.updater as updater

    handoff = (tmp_path / "handoff.json").resolve()
    monkeypatch.setattr(
        updater,
        "prepare_standalone_update",
        lambda path: (_ for _ in ()).throw(UpdateProcessWaitError("secret")),
    )

    code = main(["--handoff", str(handoff)])
    captured = capsys.readouterr()

    assert code == EXIT_PARENT_WAIT_FAILED
    assert "Nothing was installed" in captured.err
    assert "secret" not in captured.err


def test_main_reports_ready_but_explicitly_does_not_install(monkeypatch, tmp_path, capsys):
    import chitlog.updater as updater

    handoff = (tmp_path / "handoff.json").resolve()
    monkeypatch.setattr(
        updater,
        "prepare_standalone_update",
        lambda path: fake_verified(),
    )

    code = main(["--handoff", str(handoff)])
    captured = capsys.readouterr()

    assert code == EXIT_READY_NO_EXECUTION
    assert "Version 1.2.0 is ready" in captured.out
    assert "execution is not enabled" in captured.out


def test_step7b_production_sources_do_not_launch_or_terminate_processes():
    project = Path(__file__).resolve().parents[1]
    updater_source = (
        project / "chitlog/updater.py"
    ).read_text(encoding="utf-8")
    wait_source = (
        project / "chitlog/core/update_process_wait.py"
    ).read_text(encoding="utf-8")

    combined = updater_source + "\n" + wait_source

    for forbidden in (
        "subprocess",
        "Popen",
        "os.startfile",
        "ShellExecute",
        "QProcess",
        "TerminateProcess",
        "taskkill",
        "CreateProcess",
    ):
        assert forbidden not in combined

    assert "load_and_verify_update_handoff" in updater_source
    assert "wait_for_process_exit" in updater_source
    assert updater_source.count("verifier(handoff_path)") == 2
