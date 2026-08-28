"""
Regression test for _emit_conn_event() seeding an initial confirmed
state on the very first check, instead of only ever firing on state
transitions.

Real gap found live on the MA sibling project, 2026-08-28 (the new
ADB Connection chip -- same architecture here): a device reachable via
adb from the very start of a run (the common case) never produced a
single connection_lost/connection_lost_resolved event, since
_emit_conn_event only fires on a transition and the initial "was" state
defaults to False (same as "reachable" -> no transition ever recorded).
The dashboard chip stayed stuck at its default pending/grey state for
the run's entire duration, with nothing to show, even though the
device was fine the whole time. BT Signal happened to dodge this
historically only because the hourly scheduled BT-disconnect test
forces an early transition; there's no equivalent forced cycle for
plain ADB reachability.

Run: .venv/bin/pytest tests/test_conn_chip_shows_initial_state.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


def _make_driver():
    drv = object.__new__(driver_mod.AndroidDriver)
    drv._conn_state = {}
    drv.reporter = _FakeReporter()
    drv.screenshot = lambda name: None
    return drv


def test_first_check_emits_resolved_event_when_already_fine():
    """The exact real gap: first-ever check, device already reachable
    (detected=False for connection_lost) -- must still emit a
    confirming event so the chip has something to show, not silently
    do nothing."""
    drv = _make_driver()

    drv._emit_conn_event("connection_lost", False, "ADB connection lost")

    assert ("connection_lost_resolved", {"desc": "ADB connection lost"}) in drv.reporter.events


def test_first_check_emits_problem_event_when_already_broken():
    """Symmetric case: first-ever check finds a real problem -- must
    still fire the "detected" event (this already worked before the
    fix, kept as a negative-control-adjacent sanity check)."""
    drv = _make_driver()

    drv._emit_conn_event("connection_lost", True, "ADB connection lost")

    assert ("connection_lost", {"desc": "ADB connection lost"}) in drv.reporter.events


def test_second_check_with_no_change_does_not_re_emit():
    """Negative control: after the first-check seed, subsequent checks
    with no real transition must go back to being silent (no log spam)."""
    drv = _make_driver()

    drv._emit_conn_event("connection_lost", False, "ADB connection lost")
    drv.reporter.events.clear()
    drv._emit_conn_event("connection_lost", False, "ADB connection lost")

    assert drv.reporter.events == []


def test_genuine_transition_after_first_check_still_fires():
    """A real transition after the initial seed must still be reported
    normally."""
    drv = _make_driver()

    drv._emit_conn_event("connection_lost", False, "ADB connection lost")  # seed
    drv.reporter.events.clear()
    drv._emit_conn_event("connection_lost", True, "ADB connection lost")  # real drop

    assert ("connection_lost", {"desc": "ADB connection lost"}) in drv.reporter.events
