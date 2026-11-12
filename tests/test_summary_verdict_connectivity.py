"""
Regression test: summary.html's PASS/FAIL badge must count failed BT-off /
airplane-mode tests, not only symptom injections (review 2026-11-12).

Before, a run with every injection passing but a BT cycle that never got BT
back on (bt_disconnect_failed) still showed a green PASS.

Run: .venv/bin/pytest tests/test_summary_verdict_connectivity.py -v
"""
import json
import os

from src.reporter import RunReporter


def _render(tmp_path, extra):
    events = [
        {"ts": "2026-11-12T09:00:00", "event": "run_start", "data": {}},
        {"ts": "2026-11-12T09:05:00", "event": "job_result", "data": {"success": True}},
        *extra,
        {"ts": "2026-11-12T12:00:00", "event": "run_complete", "data": {"status": "ok"}},
    ]
    with open(tmp_path / "events.jsonl", "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    RunReporter(str(tmp_path), "verdict-run").render_html_summary()
    return open(os.path.join(tmp_path, "summary.html"), encoding="utf-8").read()


def _badge(html):
    return "PASS" if "badge ok" in html else "FAIL"


def test_bt_restore_failure_makes_the_run_fail(tmp_path):
    html = _render(tmp_path, [
        {"ts": "2026-11-12T10:00:00", "event": "bt_disconnect_start", "data": {"minutes": 2}},
        {"ts": "2026-11-12T10:02:00", "event": "bt_disconnect_failed",
         "data": {"phase": "restore", "error": "BT still off"}},
    ])
    assert _badge(html) == "FAIL"
    assert "0/1" in html and "BT tests passed" in html


def test_airplane_failure_makes_the_run_fail(tmp_path):
    html = _render(tmp_path, [
        {"ts": "2026-11-12T10:00:00", "event": "airplane_mode_failed", "data": {"phase": "enable"}},
    ])
    assert _badge(html) == "FAIL"


def test_passed_and_stopped_connectivity_tests_keep_pass(tmp_path):
    html = _render(tmp_path, [
        {"ts": "2026-11-12T10:00:00", "event": "bt_disconnect_done", "data": {"minutes": 2}},
        {"ts": "2026-11-12T11:00:00", "event": "airplane_mode_aborted", "data": {"minutes": 2}},
    ])
    assert _badge(html) == "PASS"
    assert "1/1" in html and "Injections passed" in html
