"""
Regression test for check_adb_connection() being callable independently
of check_connectivity() (2026-09-03, ported from the MA sibling project).

Real gap found live on MA: main.py's connectivity monitor skips
check_connectivity() entirely whenever the device is "owned" (a
scheduled job, BT/airplane test, or injection in progress) -- correct
for the UI-touching checks inside it, but a stuck app-log-capture job
(adb pull failing/retrying for minutes) meant _job_busy stayed set the
whole time, and the "ADB Connection" dashboard chip never updated even
though the phone was actually disconnected for that entire window.
check_adb_connection() was split out specifically so it can be called on
every monitor tick regardless of device ownership -- it's a pure `adb
devices` shell call, unrelated to Appium/UI, so it can't conflict with
whatever a job is doing. AK shares this exact architecture.

Run: .venv/bin/pytest tests/test_adb_connection_survives_job_busy.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


def _make_driver(monkeypatch, reachable: bool):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "RF9R503211R"}
    drv.reporter = _FakeReporter()
    monkeypatch.setattr(drv, "_adb_device_reachable", lambda: reachable)
    return drv


def test_check_adb_connection_does_not_require_conn_state_preexisting():
    """Calling check_adb_connection() before check_connectivity() has ever
    run (no self._conn_state yet) must not raise -- this is exactly the
    scenario where a job goes busy from the very start of a run, before
    any idle tick ever gets a chance to initialize it."""
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "RF9R503211R"}
    drv.reporter = _FakeReporter()
    drv._adb_device_reachable = lambda: True
    assert not hasattr(drv, "_conn_state")
    drv.check_adb_connection()  # must not raise
    assert hasattr(drv, "_conn_state")


def test_check_adb_connection_emits_lost_when_unreachable(monkeypatch):
    drv = _make_driver(monkeypatch, reachable=False)
    drv.check_adb_connection()
    assert ("connection_lost", {"desc": "ADB connection lost"}) in drv.reporter.events


def test_check_adb_connection_emits_resolved_when_reachable(monkeypatch):
    drv = _make_driver(monkeypatch, reachable=True)
    drv.check_adb_connection()
    assert ("connection_lost_resolved", {"desc": "ADB connection lost"}) in drv.reporter.events


def test_check_adb_connection_updates_even_while_job_busy():
    """The actual bug: a caller (main.py's monitor loop) must be able to
    invoke this independently of the device_owned/job_busy gate that
    guards the rest of check_connectivity(). This test only asserts the
    method itself has no dependency on any "busy" flag -- the real fix is
    in main.py calling it unconditionally, which isn't unit-testable
    without spinning up the whole monitor thread; this pins the
    contract check_adb_connection() must uphold for that to work."""
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "RF9R503211R"}
    drv.reporter = _FakeReporter()
    drv._job_busy_marker = True  # arbitrary attribute simulating "a job is running"
    drv._adb_device_reachable = lambda: False
    drv.check_adb_connection()
    assert ("connection_lost", {"desc": "ADB connection lost"}) in drv.reporter.events
