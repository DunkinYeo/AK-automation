"""
Regression tests for issue #51: study_completed_ios wasn't confirmed to
reach the dashboard/report the same way study_completed does.

Investigation found the generic "<name>_ios" -> "<name>" normalization
already added for issue #23/#24 (web/app.py's read_events(), mirrored in
src/reporter.py's own event loader) covers this event too, same as it
already covers run_complete/run_failed (issue #23 was itself a
misdiagnosis for that exact reason). These tests lock that behavior in
for study_completed_ios specifically, since #51 asked for it explicitly.

Run: .venv/bin/pytest tests/test_ios_event_normalization.py -v
"""
import json

import web.app as app_mod
from src.reporter import RunReporter

_IOS_STUDY_EVENTS = [
    {"ts": "2026-08-12T09:00:00", "event": "run_start",
     "data": {"duration_hours": 24, "interval_hours": 4}},
    {"ts": "2026-08-12T09:00:05", "event": "device_info_ios",
     "data": {"model": "iPhone 13 mini", "ios_version": "17.0", "udid": "00008110-xxx"}},
    {"ts": "2026-08-12T10:00:00", "event": "study_progress_ios", "data": {"percent": 50}},
    {"ts": "2026-08-12T11:00:00", "event": "study_completed_ios",
     "data": {"upload_percent": 99, "study_start": "2026-08-11T11:00:00",
              "study_end": "2026-08-12T11:00:00"}},
    {"ts": "2026-08-12T11:00:05", "event": "job_skipped_study_ended_ios", "data": {}},
    {"ts": "2026-08-12T11:00:10", "event": "run_ended_study_complete_ios", "data": {}},
]


def _write_events(out_dir, records):
    with open(out_dir / "events.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_read_events_normalizes_study_completed_ios(tmp_path):
    _write_events(tmp_path, _IOS_STUDY_EVENTS)
    events = app_mod.read_events(str(tmp_path))
    names = [e["event"] for e in events]
    assert "study_completed" in names
    assert "study_completed_ios" not in names


def test_report_html_shows_completed_for_ios_study_completion(tmp_path):
    """/api/report's study card must render iOS completion details, not
    just Android's plain "study_completed"."""
    _write_events(tmp_path, _IOS_STUDY_EVENTS)
    events = app_mod.read_events(str(tmp_path))
    html = app_mod._build_report_html(events)
    assert "completed" in html
    assert "99" in html  # upload_percent from the iOS event's data


def test_report_html_study_card_not_completed_without_ios_completion(tmp_path):
    """Negative control: an iOS run with no completion event yet must not
    falsely show the study card as completed."""
    events = [e for e in _IOS_STUDY_EVENTS if e["event"] != "study_completed_ios"]
    _write_events(tmp_path, events)
    normalized = app_mod.read_events(str(tmp_path))
    html = app_mod._build_report_html(normalized)
    assert "50%" in html  # falls back to last study_progress_ios reading


def test_summary_html_shows_study_completed_row_for_ios(tmp_path):
    """Saved summary.html (RunReporter, separate from /api/report) must
    also reflect an iOS run's completion — not just show PASS/FAIL badge
    correctly (already covered by test_terminal_event.py) but actually
    carry the study_completed row and device info through."""
    _write_events(tmp_path, _IOS_STUDY_EVENTS)
    reporter = RunReporter(str(tmp_path), "test-ios-run")
    reporter.render_html_summary()

    summary_html = (tmp_path / "summary.html").read_text(encoding="utf-8")
    assert "PASS" in summary_html
    assert "study_completed" in summary_html
    assert "iPhone 13 mini" in summary_html
