"""
Regression test for issue #39: when escalating recovery (_attempt_recovery)
failed during the session-check or foreground steps of
_run_with_health_check_inner, the resulting RuntimeError was never caught
at those call sites (only the UI-health-check step caught it) — it
propagated all the way out to _job()'s outer `except Exception: pass` in
_run_interval(), so the job vanished with no job_failed/job_result ever
logged. Real incident: output/ios_20260730_134931/events.jsonl shows two
hourly jobs (06:14, 07:14) with a job_start and a session_recovery_failed
but no job_result at all.

Run: .venv/bin/pytest tests/test_job_recovery_result_logging.py -v
"""
from src.scheduler import _run_with_health_check_inner


class FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))

    def has(self, name):
        return any(n == name for n, _ in self.events)


class AlwaysFailingDriver:
    """Every driver call fails — forces _attempt_recovery to exhaust all
    3 escalating steps and raise RuntimeError, exactly like the real WDA
    port-conflict incident did."""

    _study_completed = False

    def ensure_session(self):
        raise RuntimeError("session not alive")

    def ensure_ui_automation(self):
        raise RuntimeError("uiautomator2 proxy unreachable")

    def recover_session(self, step):
        raise RuntimeError(f"recover_session step {step} failed")

    def bring_to_foreground(self):
        raise RuntimeError("foreground failed")

    def wait_idle(self, seconds):
        pass

    def assert_ui_health(self):
        raise RuntimeError("ui health failed")


def test_session_check_recovery_failure_still_logs_job_result():
    """The exact real-world case: step 1 (ensure_session) fails, escalating
    recovery also fails — job_result must still be logged (success=False),
    not silently dropped."""
    reporter = FakeReporter()
    driver = AlwaysFailingDriver()

    result = _run_with_health_check_inner(
        job_callable=lambda **kw: None,
        driver=driver,
        at_hour=None,
        payload=None,
        reporter=reporter,
        cooldown_seconds=0,
    )

    assert result.success is False
    assert reporter.has("job_result"), (
        "job_result must be logged even when recovery fails at the "
        "session-check step — this is the exact silent-loss bug from #39"
    )
    assert reporter.has("job_failed")


def test_foreground_recovery_failure_still_logs_job_result():
    """Same bug class, but at the 'bring app to foreground' step."""

    class DriverFailsAtForeground(AlwaysFailingDriver):
        def ensure_session(self):
            pass  # step 1 passes...

    reporter = FakeReporter()
    driver = DriverFailsAtForeground()

    result = _run_with_health_check_inner(
        job_callable=lambda **kw: None,
        driver=driver,
        at_hour=None,
        payload=None,
        reporter=reporter,
        cooldown_seconds=0,
    )

    assert result.success is False
    assert reporter.has("job_result")
    assert reporter.has("job_failed")


def test_ui_health_recovery_failure_still_logs_job_result():
    """The pre-existing (already-correct) path — confirms the fix didn't
    change step 3's behavior."""

    class DriverFailsAtUiHealth(AlwaysFailingDriver):
        def ensure_session(self):
            pass

        def bring_to_foreground(self):
            pass

    reporter = FakeReporter()
    driver = DriverFailsAtUiHealth()

    result = _run_with_health_check_inner(
        job_callable=lambda **kw: None,
        driver=driver,
        at_hour=None,
        payload=None,
        reporter=reporter,
        cooldown_seconds=0,
    )

    assert result.success is False
    assert reporter.has("job_result")
    assert reporter.has("job_failed")
