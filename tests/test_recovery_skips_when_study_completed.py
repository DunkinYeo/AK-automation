"""
Regression test for a bug found via a real 24h iOS soak
(output/ios_20260731_145306, 2026-07-31 ~ 08-01): once the app study
completed, 16 of the next 17 hourly jobs failed with "Session recovery
failed after 3 steps" instead of cleanly skipping — only the very first
post-completion job skipped correctly.

Root cause: _attempt_recovery() (src/scheduler.py, shared Android/iOS
code) re-verifies each of its 3 escalating steps by calling
driver.assert_ui_health() and treating ANY exception as "still
unhealthy, try the next step" — including the RuntimeError("study
completed...") that assert_ui_health() itself raises once the driver has
detected the Study Overview screen (issue #18). So whenever step 1
(ensure_session) failed for an unrelated reason (an Appium timeout, a WDA
hiccup — real causes seen in the same soak run), recovery kicked in,
burned all 3 steps hitting "study completed" each time, and finally
raised a fake "Session recovery failed" instead of just recognizing
nothing needed recovering.

Run: .venv/bin/pytest tests/test_recovery_skips_when_study_completed.py -v
"""
from src.scheduler import _attempt_recovery, _run_with_health_check_inner


class FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))

    def has(self, name):
        return any(n == name for n, _ in self.events)

    def count(self, name):
        return sum(1 for n, _ in self.events if n == name)


class StudyCompletedDriver:
    """Stands in for a driver that already detected study completion
    (self._study_completed = True) but whose session-level calls can
    still transiently fail for unrelated reasons (Appium timeout, WDA
    hiccup) — exactly what happened in the real incident."""

    _study_completed = True

    def __init__(self, fail_ensure_session_once=False):
        self._ensure_session_calls = 0
        self._fail_ensure_session_once = fail_ensure_session_once

    def ensure_session(self):
        self._ensure_session_calls += 1
        if self._fail_ensure_session_once and self._ensure_session_calls == 1:
            raise RuntimeError("HTTPConnectionPool: Read timed out. (read timeout=120)")

    def bring_to_foreground(self):
        pass

    def wait_idle(self, seconds):
        pass

    def assert_ui_health(self):
        # Mirrors the real IOSDriver.assert_ui_health() once
        # _study_completed is set (issue #18).
        raise RuntimeError("study completed — app is on the Study Overview screen")

    def recover_session(self, step):
        raise AssertionError("recover_session must not be called once study is already completed")


def test_attempt_recovery_returns_immediately_when_study_already_completed():
    reporter = FakeReporter()
    driver = StudyCompletedDriver()

    _attempt_recovery(driver, reporter, cooldown_seconds=0)  # must not raise

    assert reporter.has("recovery_skipped_study_ended")
    assert reporter.count("recovery_step_start") == 0, (
        "must not have attempted any of the 3 escalating steps — there's "
        "nothing to recover to once the study is over"
    )
    assert not reporter.has("session_recovery_failed")


def test_job_skips_cleanly_when_session_check_fails_after_study_completed():
    """The exact real-world sequence: step 1 (ensure_session) fails once
    for an unrelated reason, triggering recovery — which must recognize
    study completion and let the job reach step 3's existing skip logic,
    instead of burning all 3 steps and failing the job."""
    reporter = FakeReporter()
    driver = StudyCompletedDriver(fail_ensure_session_once=True)

    result = _run_with_health_check_inner(
        job_callable=lambda **kw: None,
        driver=driver,
        at_hour=None,
        payload=None,
        reporter=reporter,
        cooldown_seconds=0,
    )

    assert result.success is True
    assert "study ended" in result.reason
    assert not reporter.has("job_failed")
    assert not reporter.has("session_recovery_failed")
