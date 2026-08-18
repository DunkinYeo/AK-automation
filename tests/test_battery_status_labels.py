"""
Regression tests for the patch battery status label list in
AndroidDriver.check_connectivity() (src/driver.py).

Found live (2026-08-12) on a run whose device showed "Normal" on its
Battery card: the recognized label list was ["Good", "Low", "Critical",
"Full", "Replace"] and had never included "Normal" since the feature's
first commit, so a genuinely healthy reading never matched anything —
the dashboard stayed stuck on stale battery status (in this case "Not
Connected" from an earlier BT-off window) for 54+ minutes with the BT
connection fully restored the whole time. Separately, "Replace" was
removed entirely: the app has no such real status text, it only ever
matched the always-on-screen "How to Replace the Battery" tutorial
card, which used to need its own disambiguation guard to avoid false
positives — simpler to just never treat it as a real status.

Run: .venv/bin/pytest tests/test_battery_status_labels.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


def _make_driver(visible_texts: set[str]):
    """A minimal AndroidDriver stand-in: real __init__ opens an Appium
    session, so we bypass it and wire up just what check_connectivity()
    touches."""
    drv = object.__new__(driver_mod.AndroidDriver)
    drv._conn_state = {}
    drv.reporter = _FakeReporter()
    drv.sel = {"symptom_add_text": "Log Symptoms"}
    drv.dismiss_unexpected_popups = lambda: False
    drv._adb_bt_off = lambda: False
    drv._adb_wifi_off = lambda: False
    drv._try_add_diary_bt_off = lambda: None
    drv._verify_ecg_after_reconnect = lambda: None
    drv.is_visible_text = lambda t, contains=True, timeout=2: (
        any(v in t for v in visible_texts) if contains else t in visible_texts
    )
    return drv


def test_normal_battery_status_is_recognized():
    drv = _make_driver({"Normal"})
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") == "Normal"
    assert ("battery_status", {"status": "Normal"}) in drv.reporter.events


def test_good_battery_status_still_recognized():
    """Existing label, must not have been dropped by the fix."""
    drv = _make_driver({"Good"})
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") == "Good"


def test_replace_text_never_reported_as_battery_status():
    """Negative control: "Replace" (only ever real as part of the "How to
    Replace the Battery" card) must not be treated as a battery status,
    even when it's the only battery-adjacent text visible."""
    drv = _make_driver({"Replace"})
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") is None
    assert not any(name == "battery_status" for name, _ in drv.reporter.events)


def test_no_recognized_label_visible_leaves_status_unset():
    """Sanity check: an unrelated screen with none of the recognized
    labels visible must not spuriously set a battery status."""
    drv = _make_driver(set())
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") is None
