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
    screen-restore + app-log capture) takes a noticeable amount of time."""

    def __init__(self, wait_seconds=0.4):
        self._wait_seconds = wait_seconds
        self._exited = False

    def poll(self):
        return 0 if self._exited else None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        time_mod.sleep(self._wait_seconds)
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


def test_status_responds_immediately_and_shows_stopped_during_teardown(monkeypatch):
    proc = _FakeProc(wait_seconds=0.5)
    _prep_state(monkeypatch, proc)
    client = app_mod.app.test_client()

    result = {}
    t = threading.Thread(target=lambda: result.__setitem__("resp", client.post("/api/stop")))
    t.start()
    time_mod.sleep(0.1)  # let /api/stop acquire+release its brief lock and enter the slow wait

    start = time_mod.monotonic()
    status = client.get("/api/status")
    elapsed = time_mod.monotonic() - start

    assert elapsed < 0.3, f"/api/status blocked for {elapsed:.2f}s -- still queued behind /api/stop's lock"
    assert status.get_json()["running"] is False

    t.join(timeout=3)
    assert result["resp"].status_code == 200


def test_second_start_still_blocked_while_teardown_in_progress(monkeypatch):
    """Negative-control-adjacent: /api/status reporting "stopped" early
    must not also let a second /api/start race in and spawn a duplicate
    process onto the same device before the first one has actually
    exited (same concern as issue #16/#33)."""
    proc = _FakeProc(wait_seconds=0.5)
    _prep_state(monkeypatch, proc)
    client = app_mod.app.test_client()

    t = threading.Thread(target=lambda: client.post("/api/stop"))
    t.start()
    time_mod.sleep(0.1)

    assert app_mod._run_already_active() is True

    t.join(timeout=3)


def test_state_fully_cleared_after_teardown_completes(monkeypatch):
    proc = _FakeProc(wait_seconds=0.1)
    _prep_state(monkeypatch, proc)
    client = app_mod.app.test_client()

    resp = client.post("/api/stop")

    assert resp.status_code == 200
    assert app_mod._state["proc"] is None
    assert app_mod._state["pid"] is None
    assert app_mod._state["stopping"] is False
    assert app_mod._run_already_active() is False
