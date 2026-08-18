"""
Regression tests for checking app study completion more often once the
study is nearly done (src/driver.py's check_connectivity()).

Raised 2026-08-12: study progress/completion normally only gets checked
once per scheduled job's UI health check (hourly by default) -- the
until_study_end scheduler loop already polls the _study_completed flag
every 10s (scheduler.py), so the real bottleneck was purely how rarely
that flag got a chance to be set. A run that had actually finished on
the phone could take up to an hour for the automation to notice.

Fix: once the last known study_progress reading is >=95% (same
threshold study_end_warning already uses), the 30s connectivity monitor
also runs the check -- left off before 95% so this doesn't add overhead
to the vast majority of a multi-day run's duration.

Run: .venv/bin/pytest tests/test_study_completion_frequent_check.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def log_event(self, name, data):
        pass


def _make_driver(last_study_pct=None, study_completed=False):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv._conn_state = {}
    drv.reporter = _FakeReporter()
    drv.sel = {"symptom_add_text": "Log Symptoms"}
    drv.dismiss_unexpected_popups = lambda: False
    drv._adb_bt_off = lambda: False
    drv._adb_wifi_off = lambda: False
    drv._try_add_diary_bt_off = lambda: None
    drv._verify_ecg_after_reconnect = lambda: None
    drv.is_visible_text = lambda t, contains=True, timeout=2: False
    if last_study_pct is not None:
        drv._last_study_pct = last_study_pct
    drv._study_completed = study_completed

    drv._study_progress_calls = 0
    drv._study_completed_calls = 0

    def _fake_report_study_progress():
        drv._study_progress_calls += 1

    def _fake_detect_study_completed():
        drv._study_completed_calls += 1
        return drv._study_completed

    drv._report_study_progress = _fake_report_study_progress
    drv._detect_study_completed = _fake_detect_study_completed
    return drv


def test_no_extra_check_below_95_percent():
    drv = _make_driver(last_study_pct=80)
    drv.check_connectivity()
    assert drv._study_progress_calls == 0
    assert drv._study_completed_calls == 0


def test_no_extra_check_when_no_reading_yet():
    """Sanity check: before _report_study_progress() has ever set
    _last_study_pct, the gate must default closed, not raise."""
    drv = _make_driver(last_study_pct=None)
    drv.check_connectivity()
    assert drv._study_progress_calls == 0
    assert drv._study_completed_calls == 0


def test_extra_check_runs_at_95_percent_and_above():
    drv = _make_driver(last_study_pct=95)
    drv.check_connectivity()
    assert drv._study_progress_calls == 1
    assert drv._study_completed_calls == 1


def test_extra_check_runs_above_95_percent():
    drv = _make_driver(last_study_pct=99)
    drv.check_connectivity()
    assert drv._study_progress_calls == 1
    assert drv._study_completed_calls == 1


def test_no_extra_check_once_already_completed():
    """Once _study_completed is already True, no need to keep re-checking
    every 30s -- harmless either way since both calls are no-ops by then,
    but confirms the gate gets this stop condition right."""
    drv = _make_driver(last_study_pct=100, study_completed=True)
    drv.check_connectivity()
    assert drv._study_progress_calls == 0
    assert drv._study_completed_calls == 0
