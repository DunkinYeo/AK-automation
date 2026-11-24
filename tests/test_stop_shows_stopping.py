"""
Stop → OK once must show "Stopping…" until the run's cleanup ends (2026-11-24).

/api/status used to return running:true during the teardown: with a real
run's run_start in events.jsonl and no terminal event yet, "no terminal event
→ running" overrode the stopping state. The page kept a live Stop button, so
testers clicked Stop again; a second SIGTERM then cut the cleanup short.

Run: .venv/bin/pytest tests/test_stop_shows_stopping.py -v
"""
import threading
from pathlib import Path

import pytest

import src.main as main_mod
import web.app as app_mod
from tests.test_stop_does_not_block_status import _FakeProc, _prep_state


def _live_run(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    proc = _FakeProc(started, release)
    _prep_state(monkeypatch, proc)
    (tmp_path / "events.jsonl").write_text('{"ts": "2026-11-24T15:00:00", "event": "run_start", "data": {}}\n')
    monkeypatch.setitem(app_mod._state, "out_dir", str(tmp_path))
    monkeypatch.setattr(app_mod, "appium_ok", lambda: True)
    return proc, started, release, app_mod.app.test_client()


def test_status_reports_stopping_not_running_during_teardown(tmp_path, monkeypatch):
    proc, started, release, c = _live_run(tmp_path, monkeypatch)
    assert c.get("/api/status").get_json()["running"] is True
    t = threading.Thread(target=lambda: c.post("/api/stop"))
    t.start()
    assert started.wait(5)
    s = c.get("/api/status").get_json()
    assert s["running"] is False and s["stopping"] is True
    release.set()
    t.join(5)
    s = c.get("/api/status").get_json()
    assert s["running"] is False and s["stopping"] is False


def test_second_stop_sends_no_second_signal(tmp_path, monkeypatch):
    proc, started, release, c = _live_run(tmp_path, monkeypatch)
    sent = []
    proc.terminate = lambda: sent.append("TERM")
    first = {}
    t = threading.Thread(target=lambda: first.__setitem__("r", c.post("/api/stop")))
    t.start()
    assert started.wait(5)
    assert c.post("/api/stop").get_json() == {"ok": True, "already_stopping": True}
    release.set()
    t.join(5)
    assert first["r"].status_code == 200 and sent == ["TERM"]


def test_only_the_first_sigterm_exits(monkeypatch):
    monkeypatch.setattr(main_mod, "_sigterm_seen", False)
    with pytest.raises(SystemExit) as e:
        main_mod._sigterm_once()
    assert e.value.code == 143
    main_mod._sigterm_once()                     # ignored: the cleanup goes on


def test_page_disables_stop_on_the_first_click_and_follows_stopping():
    page = (Path(app_mod.__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
    stop = page[page.index("async function stopTest()"):]
    stop = stop[:stop.index("\n}\n")]
    assert stop.index("setUIStopping()") < stop.index("fetch('/api/stop'")
    assert "already_stopping" in stop
    poll = page[page.index("async function poll()"):]
    assert "if (s.stopping)" in poll[:poll.index("\n}\n")]
