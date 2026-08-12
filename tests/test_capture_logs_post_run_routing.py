"""
Regression tests for /api/capture-logs routing a post-run manual capture
into the last-known run's own output dir instead of the disconnected
standalone artifacts/ location, when that run's directory is still known
(cleared only by /api/start or an explicit /api/stop -- so a run that
ended naturally, e.g. study completed, still gets associated).

Raised 2026-08-12, especially relevant now that a normal study
completion skips the automatic run-end capture (main.py's
_maybe_capture_logs_at_run_end) specifically to avoid disturbing the
Upload/Skip screen -- without this, a tester's manual catch-up capture
afterward would silently vanish from that run's report/log-timeline.

Run: .venv/bin/pytest tests/test_capture_logs_post_run_routing.py -v
"""
import json

import web.app as app_mod


class _FakeCompletedProcess:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0


def test_post_run_capture_routes_into_known_run_dir(tmp_path, monkeypatch):
    # api_capture_logs() resolves the returned zip path relative to ROOT
    # (for the download URL) -- point ROOT at tmp_path so a fake zip path
    # under it resolves cleanly instead of raising ValueError.
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    run_dir = tmp_path / "output" / "20260812_090358"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        json.dumps({"ts": "2026-08-12T09:00:00", "event": "run_start", "data": {}}) + "\n"
    )

    monkeypatch.setattr(app_mod, "_run_already_active", lambda: False)
    monkeypatch.setitem(app_mod._state, "out_dir", str(run_dir))

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        out_arg = cmd[cmd.index("--out") + 1]
        zip_path = f"{out_arg}/deadbeef-0000-0000-0000-000000000000.zip"
        return _FakeCompletedProcess(stdout=f"CAPTURE_OK:{zip_path}\n")

    monkeypatch.setattr(app_mod.subprocess, "run", fake_run)

    client = app_mod.app.test_client()
    resp = client.post("/api/capture-logs", json={"device": "RF9R503211R"})
    assert resp.status_code == 200

    out_arg = captured_cmd["cmd"][captured_cmd["cmd"].index("--out") + 1]
    assert str(run_dir / "app_logs") in out_arg, "must land inside the run's own app_logs/, not artifacts/"

    events = [json.loads(l) for l in (run_dir / "events.jsonl").read_text().splitlines()]
    success_events = [e for e in events if e["event"] == "capture_logs_success"]
    assert len(success_events) == 1
    assert "deadbeef" in success_events[0]["data"]["zip_path"]


def test_falls_back_to_standalone_when_no_known_run_dir(tmp_path, monkeypatch):
    """Negative control: with no last-known run dir (fresh server, or one
    cleared by /api/stop), behaves exactly as before -- standalone
    artifacts/ location, no events.jsonl append attempted."""
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "_run_already_active", lambda: False)
    monkeypatch.setitem(app_mod._state, "out_dir", None)
    monkeypatch.setattr(app_mod, "APP_LOGS_DIR", tmp_path / "artifacts" / "app_logs_captures")

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        out_arg = cmd[cmd.index("--out") + 1]
        zip_path = f"{out_arg}/deadbeef-0000-0000-0000-000000000000.zip"
        return _FakeCompletedProcess(stdout=f"CAPTURE_OK:{zip_path}\n")

    monkeypatch.setattr(app_mod.subprocess, "run", fake_run)

    client = app_mod.app.test_client()
    resp = client.post("/api/capture-logs", json={"device": "RF9R503211R"})
    assert resp.status_code == 200

    out_arg = captured_cmd["cmd"][captured_cmd["cmd"].index("--out") + 1]
    assert "artifacts" in out_arg and "app_logs" not in out_arg.replace("app_logs_captures", "")


def test_falls_back_to_standalone_when_known_dir_no_longer_exists(tmp_path, monkeypatch):
    """A stale out_dir pointing at a since-deleted directory must not
    crash -- falls back to standalone, same as no out_dir at all."""
    missing_dir = tmp_path / "output" / "does_not_exist"

    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "_run_already_active", lambda: False)
    monkeypatch.setitem(app_mod._state, "out_dir", str(missing_dir))
    monkeypatch.setattr(app_mod, "APP_LOGS_DIR", tmp_path / "artifacts" / "app_logs_captures")

    def fake_run(cmd, **kwargs):
        out_arg = cmd[cmd.index("--out") + 1]
        return _FakeCompletedProcess(stdout=f"CAPTURE_OK:{out_arg}/x.zip\n")

    monkeypatch.setattr(app_mod.subprocess, "run", fake_run)

    client = app_mod.app.test_client()
    resp = client.post("/api/capture-logs", json={"device": "RF9R503211R"})
    assert resp.status_code == 200
    assert not missing_dir.exists()
