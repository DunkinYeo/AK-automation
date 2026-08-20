"""
Regression tests for /api/stop no longer holding the global lock for its
entire (up to 150s) teardown wait (web/app.py) -- real tester report,
2026-08-20: after clicking Stop, the whole dashboard looked frozen --
/api/status (needed by the 2s poll loop) also needs the same lock, so it
queued behind /api/stop for the full teardown duration. Not realizing
Stop had registered, the tester clicked Start again moments later, which
queued a second run right behind the first once the lock finally freed.

Fix: /api/stop now only briefly holds the lock to grab the proc/pid
references and set _state["stopping"] = True, then does the slow
terminate-and-wait outside the lock. /api/status checks "stopping" and
reports running:false immediately; proc/pid stay populated throughout so
_run_already_active() still correctly blocks a second Start from racing
with the in-progress teardown (issue #16/#33's same concern).

Run: .venv/bin/pytest tests/test_stop_does_not_block_status.py -v
"""
import threading
import time as time_mod

import web.app as app_mod


class _FakeProc:
    """Simulates a run process whose teardown (the real driver's
    screen-restore + app-log capture) takes a noticeable amount of time.
    Event-driven rather than a fixed sleep -- a wall-clock-duration
    assertion (e.g. "must respond in <0.3s") is inherently flaky on a
    slower/contended CI runner (confirmed: this test's first version
    failed on windows-smoke, /api/status took 2.16s under CI load even
    with the fix in place -- not a real regression, just a too-tight
    threshold). wait() blocks on `release` until the test explicitly lets
    it finish, so assertions check "did this complete" rather than "did
    this complete within N seconds"."""

    def __init__(self, wait_started: threading.Event, release: threading.Event):
        self._exited = False
        self.wait_started = wait_started
        self._release = release

    def poll(self):
        return 0 if self._exited else None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        self.wait_started.set()
        self._release.wait(timeout=10)
        self._exited = True
        return 0

    def kill(self):
        self._exited = True


def _prep_state(monkeypatch, proc):
    monkeypatch.setitem(app_mod._state, "proc", proc)
    monkeypatch.setitem(app_mod._state, "pid", 12345)
    monkeypatch.setitem(app_mod._state, "start_ts", time_mod.time())
    monkeypatch.setitem(app_mod._state, "out_dir", None)
    monkeypatch.setitem(app_mod._state, "stopping", False)
    monkeypatch.setattr(app_mod, "_clear_run_state", lambda: None)
    monkeypatch.setattr(app_mod, "_clear_interval_override", lambda: None)
    monkeypatch.setattr(app_mod, "_screen_timeout_backstop", lambda: None)


def _start_stop_mid_teardown(monkeypatch):
    """Start /api/stop in a background thread and wait until its slow
    proc.wait() has genuinely begun (not just "probably has by now" --
    an explicit Event, so this holds regardless of how fast/slow the
    host is). Returns (client, stop_thread, stop_result, release_event)."""
    wait_started = threading.Event()
    release = threading.Event()
    proc = _FakeProc(wait_started, release)
    _prep_state(monkeypatch, proc)
    client = app_mod.app.test_client()

    stop_result = {}
    t_stop = threading.Thread(target=lambda: stop_result.__setitem__("resp", client.post("/api/stop")))
    t_stop.start()
    assert wait_started.wait(timeout=5), "proc.wait() never started -- /api/stop didn't reach the slow wait"
    return client, t_stop, stop_result, release


def test_status_responds_immediately_and_shows_stopped_during_teardown(monkeypatch):
    client, t_stop, stop_result, release = _start_stop_mid_teardown(monkeypatch)

    # The teardown is genuinely still blocked right now (release not set
    # yet) -- /api/status must still complete promptly rather than queue
    # behind /api/stop's lock. Bounded via thread join, not a real-time
    # duration assertion, so this isn't sensitive to how fast the host is.
    status_result = {}
    t_status = threading.Thread(target=lambda: status_result.__setitem__("resp", client.get("/api/status")))
    t_status.start()
    t_status.join(timeout=5)
    assert not t_status.is_alive(), "/api/status is still blocked -- queued behind /api/stop's lock"
    assert status_result["resp"].get_json()["running"] is False

    release.set()
    t_stop.join(timeout=5)
    assert stop_result["resp"].status_code == 200


def test_second_start_still_blocked_while_teardown_in_progress(monkeypatch):
    """Negative-control-adjacent: /api/status reporting "stopped" early
    must not also let a second /api/start race in and spawn a duplicate
    process onto the same device before the first one has actually
    exited (same concern as issue #16/#33)."""
    client, t_stop, stop_result, release = _start_stop_mid_teardown(monkeypatch)

    assert app_mod._run_already_active() is True

    release.set()
    t_stop.join(timeout=5)


def test_state_fully_cleared_after_teardown_completes(monkeypatch):
    wait_started = threading.Event()
    release = threading.Event()
    release.set()  # teardown completes immediately once wait() is called
    proc = _FakeProc(wait_started, release)
    _prep_state(monkeypatch, proc)
    client = app_mod.app.test_client()

    resp = client.post("/api/stop")

    assert resp.status_code == 200
    assert app_mod._state["proc"] is None
    assert app_mod._state["pid"] is None
    assert app_mod._state["stopping"] is False
    assert app_mod._run_already_active() is False
