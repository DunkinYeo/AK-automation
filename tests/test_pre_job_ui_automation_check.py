"""
Regression tests for wiring driver.ensure_ui_automation() into the pre-job
health check sequence (src/scheduler.py) -- real incident, 2026-08-20: a
scheduled symptom-injection job hung for ~9 minutes (cascading through
nested Appium HTTP timeouts, eventually a full 240s go_to_main() wait)
before finally failing, because nothing detected the wedged UiAutomator2
instrumentation up front.

AndroidDriver.ensure_ui_automation() (src/driver.py) was written
specifically to probe for exactly this state ("Appium can still answer
current_activity/current_package while the UiAutomator2 instrumentation
process is dead" -- its own docstring) and reconnect if so -- but it was
never actually called anywhere in the codebase, making it dead code.

Run: .venv/bin/pytest tests/test_pre_job_ui_automation_check.py -v
"""
from src.scheduler import _run_with_health_check_inner


class FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))

    def has(self, name):
        return any(n == name for n, _ in self.events)


class _HealthyDriver:
    """A normal, fully healthy driver -- every pre-job check should pass
    without needing any recovery."""

    _study_completed = False

    def __init__(self):
        self.ensure_ui_automation_calls = 0

    def ensure_session(self):
        pass

    def ensure_ui_automation(self):
        self.ensure_ui_automation_calls += 1

    def bring_to_foreground(self):
        pass

    def wait_idle(self, seconds):
        pass

    def assert_ui_health(self):
        pass


def test_ensure_ui_automation_is_actually_called_before_a_job_runs():
    """Proves the wiring exists at all -- dead code doesn't get called."""
    reporter = FakeReporter()
    driver = _HealthyDriver()

    result = _run_with_health_check_inner(
        job_callable=lambda **kw: None,
        driver=driver,
        at_hour=None,
        payload=None,
        reporter=reporter,
        cooldown_seconds=0,
    )

    assert driver.ensure_ui_automation_calls == 1, (
        "ensure_ui_automation() must be called once as part of the "
        "pre-job health check -- it existed in driver.py but was never "
        "wired up anywhere (2026-08-20 finding)"
    )
    assert result.success is True


class _WedgedThenRecoveredDriver:
    """Simulates the real incident: UiAutomator2 instrumentation is
    unresponsive (ensure_ui_automation raises, mirroring a failed
    reconnect() call inside it), but the escalating recovery successfully
    restores it -- the job should then proceed normally, not fail."""

    _study_completed = False

    def __init__(self):
        self.ensure_ui_automation_calls = 0
        self.recover_session_calls = []

    def ensure_session(self):
        pass

    def ensure_ui_automation(self):
        self.ensure_ui_automation_calls += 1
        if self.ensure_ui_automation_calls == 1:
            raise RuntimeError("uiautomator2 instrumentation not responding")

    def recover_session(self, step):
        self.recover_session_calls.append(step)
        return True  # recovered

    def bring_to_foreground(self):
        pass

    def wait_idle(self, seconds):
        pass

    def assert_ui_health(self):
        pass


def test_wedged_instrumentation_detected_and_recovered_before_job_runs():
    reporter = FakeReporter()
    driver = _WedgedThenRecoveredDriver()
    job_ran = []

    result = _run_with_health_check_inner(
        job_callable=lambda **kw: job_ran.append(True),
        driver=driver,
        at_hour=None,
        payload=None,
        reporter=reporter,
        cooldown_seconds=0,
    )

    assert reporter.has("ui_automation_check_failed")
    assert len(driver.recover_session_calls) >= 1, "recovery must actually be attempted"
    assert job_ran == [True], "the job itself must still run once recovery succeeds"
    assert result.success is True


class _WedgedAndUnrecoverableDriver(_WedgedThenRecoveredDriver):
    """Negative-control-adjacent: if recovery genuinely can't fix it, the
    job must be reported as failed, not silently skipped or hung."""

    def ensure_ui_automation(self):
        self.ensure_ui_automation_calls += 1
        raise RuntimeError("uiautomator2 instrumentation not responding")

    def recover_session(self, step):
        self.recover_session_calls.append(step)
        raise RuntimeError(f"recover_session step {step} failed")


def test_job_fails_cleanly_when_instrumentation_never_recovers():
    reporter = FakeReporter()
    driver = _WedgedAndUnrecoverableDriver()

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
