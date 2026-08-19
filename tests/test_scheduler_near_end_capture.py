"""
Feature added 2026-08-19: one extra app-log capture triggered once study
progress is nearly done (>=99%), while still on the main screen and before
the Study Overview screen ever appears. Motivated by a real gap: the
run-end capture in main.py is deliberately SKIPPED once the study is
completed (to avoid disturbing the Upload/Skip screen), and there's no
periodic automatic capture otherwise (only manual, via the web UI's
"Capture Now") -- so a run that completes naturally could otherwise end
with a log timeline no fresher than the last manual click, up to the
entire run's duration.

This drives the real scheduler (not a mock of the trigger condition) with
a background thread that raises driver._last_study_pct to 99 partway
through a short run, and asserts capture_app_logs() gets called exactly
once, before study completion, with no exception surfacing.

Run: .venv/bin/pytest tests/test_scheduler_near_end_capture.py -v
Takes ~15s (real wall-clock time — the scheduler is driven for real).
"""
import threading
import time

from src.scheduler import LongRunScheduler


class _FakeReporter:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


class _FakeDriver:
    def __init__(self):
        self._last_study_pct = 0
        self._study_completed = False
        self._job_busy = None


def test_triggers_one_capture_near_study_end(tmp_path, monkeypatch):
    import src.scheduler as scheduler_mod

    tmp_inject_file = tmp_path / "inject_now.json"
    monkeypatch.setattr(scheduler_mod, "_INJECT_NOW_FILE", tmp_inject_file)
    monkeypatch.setattr(scheduler_mod, "_CAPTURE_LOGS_REQUEST", tmp_path / "capture_logs_request.json")

    capture_calls = []

    def _fake_capture_app_logs(drv, out_dir):
        capture_calls.append((drv, str(out_dir)))
        return out_dir / "fake.zip"

    monkeypatch.setattr("src.log_capture.capture_app_logs", _fake_capture_app_logs)

    reporter = _FakeReporter(str(tmp_path))
    driver = _FakeDriver()

    scheduler = LongRunScheduler(
        duration_hours=15 / 3600,  # ~15s total run
        interval_hours=100,        # never fires on its own within the run
        start_immediately=False,
        plan=[],
        catalog=[],
        reporter=reporter,
        jitter_seconds=0,
        quiet_hours={},
        recovery_cfg={},
    )

    def _raise_progress():
        time.sleep(2)
        driver._last_study_pct = 99

    threading.Thread(target=_raise_progress, daemon=True).start()

    scheduler.run(lambda **k: None, driver=driver)

    assert len(capture_calls) == 1, f"expected exactly one capture, got {capture_calls}"
    assert capture_calls[0][0] is driver
    assert capture_calls[0][1].endswith("app_logs")
    assert ("capture_logs_triggered", {"trigger": "near_study_end"}) in reporter.events
    assert not driver._study_completed, "capture must happen before completion, not after"
