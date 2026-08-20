"""
Regression tests for log_capture.py's resilience to a transient adb/USB
conflict caused by another Mac app (real incident, 2026-08-20): Chrome's
chrome://inspect USB device inspector, and even a ChatGPT desktop app,
briefly grabbing exclusive USB access to the same Android device caused
genuine kernel-level pipe stalls that failed a bare `adb pull` outright,
and separately made the post-failure screen-recovery cleanup call land in
the same disrupted window and silently fail too -- leaving the device
found live, minutes later, stranded on the log-export flow's Folder
Information / File Information screen with an "End Study" button one
screen away.

Run: .venv/bin/pytest tests/test_log_capture_adb_retry.py -v
"""
from pathlib import Path

import src.log_capture as log_capture_mod


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_adb_run_with_retry_returns_immediately_on_success(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeResult(returncode=0)

    monkeypatch.setattr(log_capture_mod.subprocess, "run", fake_run)

    result = log_capture_mod._adb_run_with_retry(["adb", "pull", "a", "b"])

    assert result.returncode == 0
    assert calls == [["adb", "pull", "a", "b"]], "must not touch the daemon on a normal success"


def test_adb_run_with_retry_restarts_daemon_and_retries_once_on_failure(monkeypatch):
    """The exact live shape: the first attempt fails (kernel pipe stall
    from another app's USB conflict), a daemon restart is attempted, then
    the same command is retried once."""
    calls = []
    attempt = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd == ["adb", "pull", "a", "b"]:
            attempt["n"] += 1
            return _FakeResult(returncode=1 if attempt["n"] == 1 else 0, stderr="0 bytes transferred")
        return _FakeResult(returncode=0)  # kill-server / start-server

    monkeypatch.setattr(log_capture_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)

    result = log_capture_mod._adb_run_with_retry(["adb", "pull", "a", "b"])

    assert result.returncode == 0
    assert calls.count(["adb", "kill-server"]) == 1
    assert calls.count(["adb", "start-server"]) == 1
    assert calls.count(["adb", "pull", "a", "b"]) == 2, "must retry the original command exactly once"


def test_adb_run_with_retry_returns_the_final_failure_if_still_broken(monkeypatch):
    """Negative-control-adjacent: if the daemon restart doesn't help
    either, this must not loop forever or hide the failure -- return the
    (still-failed) result so the caller's own error handling fires."""
    def fake_run(cmd, **kwargs):
        if cmd == ["adb", "pull", "a", "b"]:
            return _FakeResult(returncode=1, stderr="still broken")
        return _FakeResult(returncode=0)

    monkeypatch.setattr(log_capture_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)

    result = log_capture_mod._adb_run_with_retry(["adb", "pull", "a", "b"])

    assert result.returncode == 1
    assert result.stderr == "still broken"


def test_post_capture_cleanup_retries_once_if_it_lands_in_the_same_disruption(monkeypatch):
    """The exact live incident: _ensure_menu_reachable() (called from
    capture_app_logs()'s finally block) fails on its first attempt --
    must retry once rather than silently stranding the app wherever the
    failed capture left it."""
    calls = []

    def fake_ensure_menu_reachable(drv, target_screens=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("adb call failed mid-disruption")
        # second call succeeds

    monkeypatch.setattr(log_capture_mod, "_ensure_menu_reachable", fake_ensure_menu_reachable)
    monkeypatch.setattr(log_capture_mod, "_capture_app_logs_inner",
                         lambda drv, out_dir, timeout: Path("/tmp/fake.zip"))
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)

    result = log_capture_mod.capture_app_logs(drv=object(), out_dir=Path("/tmp"), timeout=30)

    assert result == Path("/tmp/fake.zip")
    assert len(calls) == 2, "cleanup must be retried once after landing in the same disruption"


def test_post_capture_cleanup_gives_up_quietly_after_two_failed_attempts(monkeypatch):
    """Negative-control-adjacent: if the cleanup genuinely can't recover
    (not just a transient blip), this must not raise out of
    capture_app_logs() and mask the real inner result/error."""
    calls = []

    def fake_ensure_menu_reachable(drv, target_screens=None):
        calls.append(1)
        raise RuntimeError("still stuck")

    monkeypatch.setattr(log_capture_mod, "_ensure_menu_reachable", fake_ensure_menu_reachable)
    monkeypatch.setattr(log_capture_mod, "_capture_app_logs_inner",
                         lambda drv, out_dir, timeout: Path("/tmp/fake.zip"))
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)

    result = log_capture_mod.capture_app_logs(drv=object(), out_dir=Path("/tmp"), timeout=30)

    assert result == Path("/tmp/fake.zip"), "the inner result must still surface even if cleanup fails"
    assert len(calls) == 2, "must attempt exactly twice, not loop forever"
