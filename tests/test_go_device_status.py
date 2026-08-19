"""
Regression test for _go_device_status() (src/regression/connectivity.py) --
real bug caught live, 2026-08-18: the app's main screen already opens
directly on the Device Status tab (same finding driver.py's
_verify_ecg_after_reconnect made on 2026-07-15), so unconditionally
tapping "Device Status" fails once already there ("Device Status" isn't
a tappable label on its own tab) -- broke TC-CONN-001..005 outright,
5/8 connectivity suite failures on a live Pixel 7 run.

Run: .venv/bin/pytest tests/test_go_device_status.py -v
"""
from src.regression.connectivity import _go_device_status


class _FakeDriver:
    def __init__(self, dev_status_tab_visible):
        self._dev_status_tab_visible = dev_status_tab_visible
        self.tap_calls = []

    def is_visible_text(self, text, contains=True, timeout=2):
        return text == "Device Status" and self._dev_status_tab_visible

    def tap_text(self, text, timeout=5, contains=True):
        self.tap_calls.append(text)


def test_skips_tap_when_already_on_device_status(monkeypatch):
    """Common case: the main screen already IS the Device Status screen,
    so there's no "Device Status" label to tap -- must not try, since
    tapping unconditionally raised and broke every TC-CONN test."""
    monkeypatch.setattr("src.regression.connectivity.time.sleep", lambda *_: None)
    drv = _FakeDriver(dev_status_tab_visible=False)

    _go_device_status(drv)

    assert drv.tap_calls == []


def test_taps_when_a_different_tab_is_active(monkeypatch):
    """Negative control for the case above: if some other tab (e.g.
    Real-time ECG) is active and offers "Device Status" as a switch
    target, it must still actually tap to navigate there."""
    monkeypatch.setattr("src.regression.connectivity.time.sleep", lambda *_: None)
    drv = _FakeDriver(dev_status_tab_visible=True)

    _go_device_status(drv)

    assert drv.tap_calls == ["Device Status"]
