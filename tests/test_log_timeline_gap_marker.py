"""
Regression tests for the "gap" row build_log_timeline() inserts when the
captured app log's own coverage ends meaningfully before the timeline's
last row.

A tester watching a live run's /log-timeline could otherwise mistake a
stale capture (nobody's clicked "Capture App Logs" recently) for the app
having stopped logging entirely, since AUTO events keep flowing past the
point where APP rows silently stop (raised 2026-08-12).

Run: .venv/bin/pytest tests/test_log_timeline_gap_marker.py -v
"""
import zipfile

from src.log_timeline import build_log_timeline

_APP_LOG_LINE = "[Tue Aug 11 2026 00:18:48 GMT-0500] [S-Patch AccurKardia] - [Test] [Sub] app log entry\n"


def _write_app_log(out_dir, filename="capture.zip"):
    app_logs_dir = out_dir / "app_logs"
    app_logs_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(app_logs_dir / filename, "w") as zf:
        zf.writestr("logs.txt", _APP_LOG_LINE)


def _events(*ts_list):
    return [{"ts": ts, "event": "job_result", "data": {}} for ts in ts_list]


def test_gap_row_inserted_when_app_log_is_stale(tmp_path):
    """App log's only entry is 2026-08-11 00:18:48; automation events run
    two hours past that -- a real stale-capture scenario."""
    _write_app_log(tmp_path)
    events = _events("2026-08-11T00:18:00", "2026-08-11T02:18:48")
    tl = build_log_timeline(str(tmp_path), events, "2026-08-11T00:00:00", "2026-08-11T02:18:48")

    assert tl["app_log_last_ts"] == "2026-08-11T00:18:48"
    gap_rows = [r for r in tl["rows"] if r["source"] == "gap"]
    assert len(gap_rows) == 1
    assert "00:18:48" in gap_rows[0]["ts"]


def test_no_gap_row_when_app_log_is_fresh(tmp_path):
    """Negative control: the normal case (e.g. summary.html, where the
    automatic end-of-run capture lands within seconds of the last event)
    must not get a spurious gap row."""
    _write_app_log(tmp_path)
    events = _events("2026-08-11T00:18:00", "2026-08-11T00:19:00")
    tl = build_log_timeline(str(tmp_path), events, "2026-08-11T00:00:00", "2026-08-11T00:19:00")

    assert not any(r["source"] == "gap" for r in tl["rows"])


def test_no_gap_row_when_no_app_log_captured(tmp_path):
    """Sanity check: nothing to compare against, so no gap row and no
    app_log_last_ts -- must not crash on a run with no capture at all."""
    events = _events("2026-08-11T00:18:00", "2026-08-11T02:18:48")
    tl = build_log_timeline(str(tmp_path), events, "2026-08-11T00:00:00", "2026-08-11T02:18:48")

    assert tl["app_log_last_ts"] is None
    assert not any(r["source"] == "gap" for r in tl["rows"])
