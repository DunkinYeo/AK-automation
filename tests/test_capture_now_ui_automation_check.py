"""
Regression test for wiring ensure_ui_automation() into the standalone
"Capture Now" job (src/scheduler.py's _capture_logs_job) -- real incident,
2026-08-20: unlike scheduled jobs (which gained this pre-flight check in
#110/#111), the manual "Capture Now" trigger never checked for a wedged
(not crashed) UiAutomator2 instrumentation before diving in. Live evidence:
a raw `adb screencap` worked fine throughout, but every Appium-mediated
call in the capture flow (including its own diagnostic screenshots)
silently produced nothing across two full failed attempts -- the exact
signature ensure_ui_automation() exists to catch and self-heal.

This drives the real scheduler (not a mock of the wiring) with a request-
file trigger, matching how the web UI's "Capture Now" button actually
fires this path.

Run: .venv/bin/pytest tests/test_capture_now_ui_automation_check.py -v
Takes ~15s (real wall-clock time -- the scheduler is driven for real).
"""
import json
import threading
import time
from pathlib import Path

from src.scheduler import LongRunScheduler


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))

    def has(self, name):
        return any(n == name for n, _ in self.events)


class _FakeDriver:
    _job_busy = None

    def __init__(self):
        self.ensure_ui_automation_calls = 0

    def ensure_ui_automation(self):
        self.ensure_ui_automation_calls += 1


def test_capture_now_checks_ui_automation_before_capturing(tmp_path, monkeypatch):
    import src.scheduler as scheduler_mod

    monkeypatch.setattr(scheduler_mod, "_INJECT_NOW_FILE", tmp_path / "inject_now.json")
    request_file = tmp_path / "capture_logs_request.json"
    monkeypatch.setattr(scheduler_mod, "_CAPTURE_LOGS_REQUEST", request_file)
    monkeypatch.setattr(scheduler_mod, "_CAPTURE_LOGS_RESULT", tmp_path / "capture_logs_result.json")

    capture_calls = []

    def fake_capture_app_logs(driver, out_dir):
        capture_calls.append(out_dir)
        return Path(out_dir) / "fake.zip"

    monkeypatch.setattr("src.log_capture.capture_app_logs", fake_capture_app_logs)

    reporter = _FakeReporter()
    driver = _FakeDriver()
    scheduler = LongRunScheduler(
        duration_hours=15 / 3600,
        interval_hours=100,
        start_immediately=False,
        plan=[],
        catalog=[],
        reporter=reporter,
        jitter_seconds=0,
        quiet_hours={},
        recovery_cfg={},
    )

    def trigger_capture():
        time.sleep(0.5)
        request_file.write_text(json.dumps({"out_dir": str(tmp_path)}))

    threading.Thread(target=trigger_capture, daemon=True).start()
    scheduler.run(lambda **kw: None, driver=driver)

    assert driver.ensure_ui_automation_calls == 1, (
        "ensure_ui_automation() must be checked before a manual capture "
        "attempt, same as scheduled jobs already do"
    )
    assert len(capture_calls) == 1
    assert not reporter.has("ui_automation_check_failed")
