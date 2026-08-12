"""
Regression tests for build_capture_history() (src/log_timeline.py) --
a record of when app logs were captured during a run and how (manual
mid-run click vs the automatic end-of-run capture), requested
2026-08-12 so this doesn't have to be reconstructed by hand from
events.jsonl.

Run: .venv/bin/pytest tests/test_capture_history.py -v
"""
from src.log_timeline import build_capture_history


def test_empty_when_no_captures():
    assert build_capture_history([{"ts": "t", "event": "run_start", "data": {}}]) == []


def test_manual_success_with_filename():
    events = [{
        "ts": "2026-08-12T09:37:04", "event": "capture_logs_success",
        "data": {"zip_path": "/tmp/out/app_logs/20260812_093704/abc-123.zip"},
    }]
    history = build_capture_history(events)
    assert len(history) == 1
    assert history[0] == {
        "ts": "2026-08-12T09:37:04", "outcome": "success", "trigger": "manual",
        "filename": "abc-123.zip", "detail": "",
    }


def test_run_end_success_no_zip_path():
    events = [{
        "ts": "2026-08-12T20:00:00", "event": "capture_logs_success",
        "data": {"trigger": "run_end"},
    }]
    history = build_capture_history(events)
    assert history[0]["trigger"] == "run_end"
    assert history[0]["filename"] is None


def test_failed_capture_records_error_detail():
    events = [{
        "ts": "2026-08-12T10:00:00", "event": "capture_logs_failed",
        "data": {"error": "Could not tap Download for abc: timeout"},
    }]
    history = build_capture_history(events)
    assert history[0]["outcome"] == "failed"
    assert "timeout" in history[0]["detail"]


def test_skipped_study_completed():
    events = [{
        "ts": "2026-08-12T20:05:00", "event": "capture_logs_skipped_study_completed",
        "data": {},
    }]
    history = build_capture_history(events)
    assert history[0] == {
        "ts": "2026-08-12T20:05:00", "outcome": "skipped", "trigger": "run_end",
        "filename": None, "detail": "study completed — app left on Upload/Skip screen",
    }


def test_multiple_captures_preserve_order():
    events = [
        {"ts": "t1", "event": "capture_logs_success", "data": {"zip_path": "/a/1.zip"}},
        {"ts": "t2", "event": "capture_logs_failed", "data": {"error": "x"}},
        {"ts": "t3", "event": "capture_logs_success", "data": {"trigger": "run_end", "zip_path": "/a/2.zip"}},
    ]
    history = build_capture_history(events)
    assert [c["ts"] for c in history] == ["t1", "t2", "t3"]
    assert [c["outcome"] for c in history] == ["success", "failed", "success"]


def test_unrelated_events_ignored():
    events = [
        {"ts": "t1", "event": "run_start", "data": {}},
        {"ts": "t2", "event": "job_result", "data": {"success": True}},
    ]
    assert build_capture_history(events) == []
