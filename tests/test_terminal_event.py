"""
Regression tests for issue #35: run_ended_study_complete (until_study_end
mode's early-exit signal) wasn't recognized as a terminal event anywhere,
so if run_complete never followed it (issue #34's scheduler-shutdown
deadlock — a real run hung for 21+ hours with no run_complete ever
logged), the dashboard kept reporting "running" forever regardless of
whether the underlying process was actually alive, and the saved
summary.html report showed FAIL for a run that had actually completed
successfully.

Run: .venv/bin/pytest tests/test_terminal_event.py -v
"""
import json

import web.app as app_mod
from src.reporter import RunReporter


def _events(*names):
    return [{"ts": f"2026-01-01T00:00:{i:02d}", "event": n, "data": {}}
            for i, n in enumerate(names)]


def test_terminal_event_recognizes_run_ended_study_complete():
    events = _events("run_start", "study_progress", "run_ended_study_complete")
    assert app_mod._terminal_event(events) == "run_ended_study_complete"


def test_terminal_event_still_prefers_actual_run_complete():
    events = _events("run_start", "run_ended_study_complete", "run_complete")
    assert app_mod._terminal_event(events) == "run_complete"


def test_terminal_event_none_when_run_ended_study_complete_absent():
    """Negative control: a run with no terminal signal at all must still
    report None, not accidentally match on an unrelated event."""
    events = _events("run_start", "study_progress", "job_result")
    assert app_mod._terminal_event(events) is None


def test_hub_events_marks_study_complete_as_done(tmp_path, monkeypatch):
    """/api/hub/events (the team dashboard's remote ingestion endpoint) must
    mark a session 'done', not leave it stuck on 'running', when the only
    terminal signal received is run_ended_study_complete."""
    monkeypatch.setattr(app_mod, "_hub_sessions", {})
    client = app_mod.app.test_client()
    resp = client.post("/api/hub/events", json={
        "tester_name": "test-tester",
        "event": "run_ended_study_complete",
        "ts": "2026-01-01T00:00:00",
        "data": {"duration_cap_hours": 168.0},
    })
    assert resp.status_code == 200
    assert app_mod._hub_sessions["test-tester"]["status"] == "done"


def test_summary_report_shows_pass_when_only_study_complete_logged(tmp_path):
    """reporter.py's saved summary.html must not show FAIL for a run whose
    only terminal-ish event is run_ended_study_complete (the exact
    real-world shape of the #34 hang, before run_complete could ever log)."""
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    events_path = out_dir / "events.jsonl"
    with open(events_path, "w", encoding="utf-8") as f:
        for rec in [
            {"ts": "2026-01-01T00:00:00", "event": "run_start", "data": {}},
            {"ts": "2026-01-01T00:00:01", "event": "job_result",
             "data": {"success": True}},
            {"ts": "2026-01-01T01:00:00", "event": "run_ended_study_complete",
             "data": {"duration_cap_hours": 168.0}},
        ]:
            f.write(json.dumps(rec) + "\n")

    reporter = RunReporter(str(out_dir), "test-run")
    reporter.render_html_summary()

    summary_html = (out_dir / "summary.html").read_text(encoding="utf-8")
    assert "PASS" in summary_html
    assert "FAIL" not in summary_html
