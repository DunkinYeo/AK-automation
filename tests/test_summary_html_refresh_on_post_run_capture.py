"""
Regression tests for _refresh_summary_html_if_exists() (web/app.py):
a post-run manual log capture must re-render summary.html so it -- the
durable/shareable report artifact -- doesn't stay silently stale
forever once the run's own process has already exited (requested
2026-08-12).

Run: .venv/bin/pytest tests/test_summary_html_refresh_on_post_run_capture.py -v
"""
import json

import web.app as app_mod


def _write_events(out_dir, records):
    with open(out_dir / "events.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_refreshes_summary_html_when_it_already_exists(tmp_path):
    out_dir = tmp_path / "20260812_090358"
    out_dir.mkdir()
    _write_events(out_dir, [
        {"ts": "2026-08-12T09:00:00", "event": "run_start", "data": {}},
        {"ts": "2026-08-12T15:40:56", "event": "run_complete", "data": {"status": "ok"}},
    ])
    # Simulate the report having already been rendered once at run end.
    (out_dir / "summary.html").write_text("<html>stale</html>", encoding="utf-8")

    # Add a capture event as if it had just landed, then refresh.
    with open(out_dir / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": "2026-08-12T16:07:25", "event": "capture_logs_success",
            "data": {"zip_path": str(out_dir / "app_logs" / "x.zip")},
        }) + "\n")

    app_mod._refresh_summary_html_if_exists(str(out_dir))

    refreshed = (out_dir / "summary.html").read_text(encoding="utf-8")
    assert "stale" not in refreshed
    assert "Log Captures" in refreshed


def test_no_op_when_summary_html_does_not_exist_yet(tmp_path):
    """Negative control: a still-active/never-finalized run (no
    summary.html rendered yet) must not get one spuriously created --
    that would misleadingly signal the run had finished."""
    out_dir = tmp_path / "20260812_090358"
    out_dir.mkdir()
    _write_events(out_dir, [{"ts": "2026-08-12T09:00:00", "event": "run_start", "data": {}}])

    app_mod._refresh_summary_html_if_exists(str(out_dir))

    assert not (out_dir / "summary.html").exists()
