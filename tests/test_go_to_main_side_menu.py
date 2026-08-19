"""
Regression test for go_to_main()'s handling of a leftover side-menu screen
(src/regression/helpers.py) -- real failure caught live, 2026-08-19: a prior
run's process was SIGKILLed mid app-log-capture, which navigates into the
side menu (Setting / Terms and Information / Guide) to reach the app's
hidden log-export screen. The app was left sitting there, and the next
run's go_to_main() had no case for this screen at all -- it fell through to
"unknown screen", spent the full 240s timeout trying generic dialog-dismiss
buttons that don't exist on this screen, and the run failed immediately
before ever reaching the main screen.

Run: .venv/bin/pytest tests/test_go_to_main_side_menu.py -v
"""
from src.regression import helpers


class _FakeInnerDriver:
    def get_window_size(self):
        return {"width": 1080, "height": 2400}

    def find_elements(self, *a, **k):
        return []

    def find_element(self, *a, **k):
        raise Exception("no such element")

    def activate_app(self, pkg):
        pass

    def press_keycode(self, code):
        pass


class _FakeDriver:
    """`visible` is the set of texts currently "on screen" -- close_menu()
    (stubbed) flips it to simulate the menu actually closing."""

    def __init__(self, visible):
        self.drv = _FakeInnerDriver()
        self.cfg = {"app_package": "com.wellysis.accurkardia.accurkardia.mobile",
                    "test_serial_number": "680150"}
        self.sel = {"symptom_add_text": "Log Symptoms"}
        self.visible = visible

    def is_visible_text(self, text, timeout=1, contains=True):
        texts = [text] if isinstance(text, str) else text
        return any(t in self.visible for t in texts)

    def tap_text(self, text, timeout=5, contains=True):
        pass


def test_go_to_main_closes_leftover_side_menu(monkeypatch):
    """The exact screen from the live failure: "Version Information" /
    "Terms and Information" visible, no main-screen indicator -- must
    recognize it and close the menu instead of looping to a timeout."""
    monkeypatch.setattr(helpers.time, "sleep", lambda *_: None)
    drv = _FakeDriver(visible={"Version Information", "Terms and Information"})

    def _fake_close_menu(d):
        d.visible = {"Log Symptoms"}

    monkeypatch.setattr(helpers, "close_menu", _fake_close_menu)

    helpers.go_to_main(drv, wait_ble=5)  # must return, not raise


def test_go_to_main_times_out_if_side_menu_never_closes(monkeypatch):
    """Negative-control-adjacent: if closing the menu genuinely never
    works (e.g. close_menu() itself is broken), this must still fail
    loudly with the real timeout error -- not hang forever or silently
    report success."""
    monkeypatch.setattr(helpers.time, "sleep", lambda *_: None)
    drv = _FakeDriver(visible={"Version Information", "Terms and Information"})
    monkeypatch.setattr(helpers, "close_menu", lambda d: None)  # never closes

    try:
        helpers.go_to_main(drv, wait_ble=1)
        assert False, "expected a timeout Exception"
    except Exception as e:
        assert "Main screen not reached" in str(e)
