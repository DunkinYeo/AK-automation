"""
Regression test for _maybe_capture_logs_at_run_end() (src/main.py):
run-end app-log capture must be skipped when the study completed
normally, since capture_app_logs() would navigate away from the Study
Overview (Upload/Skip) screen the tester may still need to act on
(real conflict caught live, 2026-08-12 -- scheduler.py's own recovery
already avoids this same navigation for the same reason).

Run: .venv/bin/pytest tests/test_capture_logs_skip_on_study_complete.py -v
"""
import src.main as main_mod
import src.log_capture as log_capture_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


class _FakeDriver:
    def __init__(self, study_completed):
        self._study_completed = study_completed
        self._job_busy = None


def test_capture_skipped_when_study_completed(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(
        log_capture_mod, "capture_app_logs",
        lambda drv, out: called.append(out),
    )

    reporter = _FakeReporter()
    driver = _FakeDriver(study_completed=True)
    main_mod._maybe_capture_logs_at_run_end(driver, str(tmp_path), reporter)

    assert called == []
    assert ("capture_logs_skipped_study_completed", {}) in reporter.events
    assert not any(name.startswith("capture_logs_success") or name.startswith("capture_logs_failed")
                   for name, _ in reporter.events)


def test_capture_runs_when_study_not_completed(monkeypatch, tmp_path):
    """Negative control: the normal case (run ended some other way) must
    still capture logs as before."""
    called = []
    monkeypatch.setattr(
        log_capture_mod, "capture_app_logs",
        lambda drv, out: called.append(out),
    )

    reporter = _FakeReporter()
    driver = _FakeDriver(study_completed=False)
    main_mod._maybe_capture_logs_at_run_end(driver, str(tmp_path), reporter)

    assert len(called) == 1
    assert ("capture_logs_success", {"trigger": "run_end"}) in reporter.events
    assert not any(name == "capture_logs_skipped_study_completed" for name, _ in reporter.events)
