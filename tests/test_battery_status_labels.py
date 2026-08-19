"""
Regression tests for the patch battery status reading in
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

Found live again (2026-08-19): the label search was a blind whole-screen
is_visible_text() scan for each candidate word, not scoped to the actual
Battery card at all — during an airplane-mode recovery cycle, some
unrelated on-screen text elsewhere contained "Low" and got misattributed
as the patch's battery status. Rewritten to scope matching to text
immediately adjacent to the "Battery" card's own label in page_source,
the same anchored-regex pattern already used for Study/Data Upload %
scraping elsewhere in this class.

Run: .venv/bin/pytest tests/test_battery_status_labels.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


class _FakeInnerDriver:
    def __init__(self, page_source=""):
        self.page_source = page_source


def _make_driver(page_source: str = ""):
    """A minimal AndroidDriver stand-in: real __init__ opens an Appium
    session, so we bypass it and wire up just what check_connectivity()
    touches. is_visible_text always returns False -- nothing else on
    screen (BT-off indicators, popups) is under test here."""
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
    drv.drv = _FakeInnerDriver(page_source=page_source)
    return drv


def _battery_card(value: str) -> str:
    return f'<node text="Battery"/><node text="{value}"/>'


def test_normal_battery_status_is_recognized():
    drv = _make_driver(_battery_card("Normal"))
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") == "Normal"
    assert ("battery_status", {"status": "Normal"}) in drv.reporter.events


def test_good_battery_status_still_recognized():
    """Existing label, must not have been dropped by the fix."""
    drv = _make_driver(_battery_card("Good"))
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") == "Good"


def test_replace_text_never_reported_as_battery_status():
    """Negative control: "Replace" (only ever real as part of the "How to
    Replace the Battery" card) must not be treated as a battery status,
    even directly adjacent to the "Battery" label in page_source."""
    drv = _make_driver(_battery_card("Replace"))
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") is None
    assert not any(name == "battery_status" for name, _ in drv.reporter.events)


def test_no_recognized_label_visible_leaves_status_unset():
    """Sanity check: an unrelated screen with no Battery card at all must
    not spuriously set a battery status."""
    drv = _make_driver("")
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") is None


def test_low_text_elsewhere_on_screen_not_misread_as_battery_status():
    """Real bug caught live, 2026-08-19: during an airplane-mode recovery
    cycle, some unrelated on-screen text contained "Low" and the old
    blind whole-screen scan misread it as the patch's battery status,
    even though the actual Battery card was showing "Good". Scoping to
    text adjacent to the "Battery" label must not be fooled by "Low"
    appearing somewhere unrelated on the same screen."""
    src = '<node text="Network"/><node text="Low"/>' + _battery_card("Good")
    drv = _make_driver(src)
    drv.check_connectivity()
    assert drv._conn_state.get("battery_status") == "Good"
