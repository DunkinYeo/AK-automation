"""
Regression tests for wait_for_adb_device()'s adb-daemon-restart escalation
(src/driver.py) -- real incident, 2026-08-20 (issue #62): after a WiFi<->USB
transport switch, a device vanished from `adb devices` entirely and stayed
that way through 30+ minutes of `adb get-state`/`adb connect` retries. Only
`adb kill-server && adb start-server` fixed it -- a wedged adb daemon never
recovers on its own no matter how long plain retries keep getting tried.

Run: .venv/bin/pytest tests/test_adb_daemon_restart_recovery.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


class _FakeResult:
    def __init__(self, returncode=1, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def _use_fake_clock(monkeypatch):
    state = {"now": 1_700_000_000.0}
    monkeypatch.setattr(driver_mod.time, "time", lambda: state["now"])
    monkeypatch.setattr(driver_mod.time, "sleep", lambda s: state.__setitem__("now", state["now"] + s))
    return state


def _make_driver():
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "TESTSERIAL"}
    drv.reporter = _FakeReporter()
    return drv


def test_restarts_daemon_once_and_recovers(monkeypatch):
    """The exact live shape: device unreachable, daemon restart happens
    once partway through the wait, device becomes reachable right after."""
    _use_fake_clock(monkeypatch)
    calls = []
    recovered = {"v": False}

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if "kill-server" in cmd:
            recovered["v"] = True
            return _FakeResult(returncode=0)
        if "start-server" in cmd:
            return _FakeResult(returncode=0)
        # get-state
        if recovered["v"]:
            return _FakeResult(returncode=0, stdout=b"device\n")
        return _FakeResult(returncode=1, stdout=b"")

    monkeypatch.setattr(driver_mod.subprocess, "run", fake_run)
    drv = _make_driver()

    result = drv.wait_for_adb_device(timeout=300)

    assert result is True
    assert calls.count(["adb", "kill-server"]) == 1
    assert calls.count(["adb", "start-server"]) == 1
    assert any(name == "adb_daemon_restart" for name, _ in drv.reporter.events)
    assert ("adb_reconnected", {}) in drv.reporter.events


def test_daemon_restart_attempted_only_once_when_device_never_returns(monkeypatch):
    """Negative-control-adjacent: if the device genuinely never comes back
    (daemon restart doesn't help either), this must not loop restarting
    the daemon over and over for the rest of the wait -- exactly once,
    then fall through to the existing timeout behavior."""
    _use_fake_clock(monkeypatch)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if "kill-server" in cmd or "start-server" in cmd:
            return _FakeResult(returncode=0)
        return _FakeResult(returncode=1, stdout=b"")  # never reconnects

    monkeypatch.setattr(driver_mod.subprocess, "run", fake_run)
    drv = _make_driver()

    result = drv.wait_for_adb_device(timeout=300)

    assert result is False
    assert calls.count(["adb", "kill-server"]) == 1
    assert calls.count(["adb", "start-server"]) == 1
    assert ("adb_reconnect_timeout", {"timeout_sec": 300}) in drv.reporter.events


def test_no_daemon_restart_when_device_reconnects_quickly(monkeypatch):
    """Must not restart the daemon at all for an ordinary quick
    reconnection -- only a sustained failure past the halfway point
    should ever trigger it."""
    _use_fake_clock(monkeypatch)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeResult(returncode=0, stdout=b"device\n")

    monkeypatch.setattr(driver_mod.subprocess, "run", fake_run)
    drv = _make_driver()

    result = drv.wait_for_adb_device(timeout=300)

    assert result is True
    assert not any("kill-server" in c for c in calls)
    assert not any(name == "adb_daemon_restart" for name, _ in drv.reporter.events)
