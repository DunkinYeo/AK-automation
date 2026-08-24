"""
Regression tests for a real concurrency bug found live, 2026-08-20:
_detect_study_completed() (src/driver.py) runs on the connectivity
monitor's own background daemon thread (main.py's _connectivity_monitor),
entirely independent of LongRunScheduler.run()'s main-thread loop
(src/scheduler.py), which polls driver._study_completed every 10s to
decide when an until_study_end run should end.

Real evidence (output/20260820_171010/events.jsonl): study_completed and
run_ended_study_complete/run_complete were logged in the SAME SECOND --
the main loop caught the flag and ended the run before
_handle_study_completion_action() (the Upload/Skip tap) ever got a
chance to run. Since the connectivity monitor is a daemon thread, the
ensuing process exit killed it mid-action with zero exception and zero
log -- the Upload button was silently never tapped.

Fix: driver.py sets driver._study_completion_action_done = True only
after _handle_study_completion_action() returns (success or failure);
scheduler.py's until_study_end exit path waits (bounded) for that flag
before logging run_ended_study_complete.

Run: .venv/bin/pytest tests/test_study_completion_race.py -v
"""
import threading
import time

import src.driver as driver_mod
import src.scheduler as scheduler_mod
from src.scheduler import LongRunScheduler


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))

    def has(self, name):
        return any(n == name for n, _ in self.events)


class _FakeInnerDriver:
    page_source = ""


def _make_android_driver(action_raises=False):
    """Drives the real _detect_study_completed()/_handle_study_completion_action()
    call chain in driver.py -- not a mock of the wiring itself."""
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.reporter = _FakeReporter()
    drv.cfg = {}
    drv.drv = _FakeInnerDriver()
    drv._study_complete_action = "upload"
    drv._slack_webhook = ""
    drv.is_visible_text = lambda t, contains=True, timeout=2: True
    drv.screenshot = lambda name: None

    def _fake_action(info):
        if action_raises:
            raise RuntimeError("boom")
    drv._handle_study_completion_action = _fake_action
    return drv


def test_action_done_flag_set_after_completion_action_runs():
    drv = _make_android_driver()
    assert not getattr(drv, "_study_completion_action_done", False)

    drv._detect_study_completed()

    assert drv._study_completion_action_done is True


def test_action_done_flag_set_even_if_action_raises():
    """The flag must be set via finally -- a bug in the action itself must
    never leave the scheduler waiting the full timeout for no reason."""
    drv = _make_android_driver(action_raises=True)

    drv._detect_study_completed()

    assert drv._study_completion_action_done is True


class _FakeSchedDriver:
    """_study_completed is True from the start, standing in for the
    connectivity-monitor thread (main.py) having just set it -- the real
    race window is entirely about what happens between that and
    _study_completion_action_done becoming True. Deliberately does NOT
    mock time.sleep globally: BackgroundScheduler runs its own internal
    thread that also calls time.sleep(), and turning that into a no-op
    makes it spin the GIL instead of actually pausing (measured: turned a
    ~15s test into 160s+). Real, short wall-clock delays only."""
    _study_completed = True

    def __init__(self):
        self._done = False
        self.poll_count = 0

    @property
    def _study_completion_action_done(self):
        self.poll_count += 1
        return self._done

    @_study_completion_action_done.setter
    def _study_completion_action_done(self, value):
        self._done = value


def _run_until_study_end(driver, duration_hours=1):
    reporter = _FakeReporter()
    scheduler = LongRunScheduler(
        duration_hours=duration_hours,
        interval_hours=100,
        start_immediately=False,
        plan=[],
        catalog=[],
        reporter=reporter,
        jitter_seconds=0,
        quiet_hours={},
        recovery_cfg={},
        until_study_end=True,
    )
    scheduler.run(lambda **kw: None, driver=driver)
    return reporter


def test_run_waits_for_completion_action_before_ending():
    """Real wall-clock run (~15-16s): the main loop's first 10s tick sees
    _study_completed already True. The completion action doesn't finish
    (flip _study_completion_action_done True) until 13s in -- AFTER that
    first tick -- so this can only pass if the fix actually keeps polling
    instead of ending the run on that first tick, the exact shape of the
    real incident (run_ended_study_complete logged before the action ever
    finished)."""
    driver = _FakeSchedDriver()

    def _finish_action_after_delay():
        time.sleep(13)
        driver._study_completion_action_done = True

    threading.Thread(target=_finish_action_after_delay, daemon=True).start()

    started = time.time()
    reporter = _run_until_study_end(driver)
    elapsed = time.time() - started

    assert reporter.has("run_ended_study_complete")
    assert driver._done is True, (
        "run_ended_study_complete must not be logged before the completion "
        "action actually finished"
    )
    assert elapsed >= 12, (
        f"only waited {elapsed:.1f}s -- must have actually blocked until "
        "the completion action finished (~13s), not returned immediately "
        "once _study_completed was seen"
    )


def test_run_gives_up_after_bounded_timeout_if_action_never_finishes(monkeypatch):
    """Negative-control-adjacent: a stuck completion action must not hang
    the run forever. Only time.time() is faked (jumped forward on every
    call) so the bounded wait's deadline check resolves after a handful
    of real, short time.sleep(1) calls instead of a real 320s wait --
    time.sleep() itself stays real to avoid starving BackgroundScheduler's
    own thread (see _FakeSchedDriver's docstring)."""
    driver = _FakeSchedDriver()  # _study_completion_action_done never set True

    real_time = time.time
    clock = {"t": real_time()}

    def _fake_time():
        clock["t"] += 50  # jump well past the 320s deadline in ~7 calls
        return clock["t"]

    monkeypatch.setattr(scheduler_mod.time, "time", _fake_time)

    reporter = _run_until_study_end(driver)

    assert reporter.has("run_ended_study_complete"), (
        "must still end the run after the bounded wait, not hang forever"
    )
