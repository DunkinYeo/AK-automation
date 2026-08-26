"""
Regression tests for a real gap found live, 2026-08-26: the web report's
"App Study Summary" (_build_report_html, web/app.py) read upload_percent
from the study_completed event -- the value scraped the moment the
Study Overview screen first appears, BEFORE the "On Study Completion"
auto-tap (driver.py's _handle_study_completion_action) ever runs. A
successful auto-tap Upload still left the report showing the stale
pre-tap percent and an "ACTION REQUIRED: tap Upload" callout telling a
tester to do something the automation had already done.

Run: .venv/bin/pytest tests/test_report_study_action_outcome.py -v
"""
import web.app as app_mod


def _events(*extra):
    base = [
        {"ts": "2026-01-01T00:00:00", "event": "run_start", "data": {}},
        {"ts": "2026-01-01T00:00:01", "event": "device_info", "data": {"model": "X", "udid": "U"}},
    ]
    return base + list(extra)


def test_no_action_required_when_upload_auto_tap_showed_success_screen():
    events = _events(
        {"ts": "2026-01-01T01:00:00", "event": "study_completed",
         "data": {"upload_percent": "99", "study_start": "s", "study_end": "e"}},
        {"ts": "2026-01-01T01:00:05", "event": "study_completion_action",
         "data": {"action": "upload", "upload_percent_before": "99",
                   "upload_percent_after": None, "success_screen_detected": True}},
    )

    html = app_mod._build_report_html(events, None)

    assert "ACTION REQUIRED" not in html
    assert "Uploaded (automation)" in html


def test_no_action_required_when_skip_action_taken():
    events = _events(
        {"ts": "2026-01-01T01:00:00", "event": "study_completed",
         "data": {"upload_percent": "31", "study_start": "s", "study_end": "e"}},
        {"ts": "2026-01-01T01:00:05", "event": "study_completion_action",
         "data": {"action": "skip"}},
    )

    html = app_mod._build_report_html(events, None)

    assert "ACTION REQUIRED" not in html
    assert "Skipped (automation)" in html


def test_still_shows_action_required_when_no_completion_action_taken():
    """Negative control: default "notify" mode (no study_completion_action
    event at all) must keep the original behavior -- a human really does
    need to act."""
    events = _events(
        {"ts": "2026-01-01T01:00:00", "event": "study_completed",
         "data": {"upload_percent": "31", "study_start": "s", "study_end": "e"}},
    )

    html = app_mod._build_report_html(events, None)

    assert "ACTION REQUIRED: Data upload is at 31%" in html


def test_still_shows_action_required_when_auto_tap_upload_did_not_help():
    """Negative control: if the auto-tap Upload didn't actually move the
    percent at all (the driver.py fallback-to-notify case), the report
    must still flag it exactly like plain notify mode -- not silently
    claim success."""
    events = _events(
        {"ts": "2026-01-01T01:00:00", "event": "study_completed",
         "data": {"upload_percent": "31", "study_start": "s", "study_end": "e"}},
        {"ts": "2026-01-01T01:00:05", "event": "study_completion_action",
         "data": {"action": "upload", "upload_percent_before": "31",
                   "upload_percent_after": "31", "success_screen_detected": False}},
    )

    html = app_mod._build_report_html(events, None)

    assert "ACTION REQUIRED: Data upload is at 31%" in html


def test_action_required_uses_the_post_tap_percent_when_it_partially_improved():
    """The auto-tap moved the percent but not all the way to 100 -- must
    show the fresher post-tap number, not the stale pre-tap one."""
    events = _events(
        {"ts": "2026-01-01T01:00:00", "event": "study_completed",
         "data": {"upload_percent": "31", "study_start": "s", "study_end": "e"}},
        {"ts": "2026-01-01T01:00:05", "event": "study_completion_action",
         "data": {"action": "upload", "upload_percent_before": "31",
                   "upload_percent_after": "67", "success_screen_detected": False}},
    )

    html = app_mod._build_report_html(events, None)

    assert "ACTION REQUIRED" in html
    assert "automatic Upload tap" in html
    assert "67%" in html
    assert "31%" not in html
