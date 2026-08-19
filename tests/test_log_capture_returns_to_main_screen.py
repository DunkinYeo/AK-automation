"""
Regression test for capture_app_logs()'s post-capture screen recovery
(src/log_capture.py) -- real report, 2026-08-19: after a run was stopped
mid-capture, the tester found the app stranded inside Settings /
Version Information instead of back on the main screen.

Root cause: _ensure_menu_reachable() is called both BEFORE capture (to
get to a screen where open_menu() works -- Setting/Version Information
count as success there) and AFTER capture in a finally block, with the
exact same "reachable" screen list. Since the capture flow always ends
still sitting inside Version Information (that's where the file
browser/Download button live), the post-capture call trivially
"succeeded" the instant it ran, without ever backing out of Settings.

Fix: the post-capture call now passes a narrower target_screens
(_MAIN_SCREENS, excluding Setting/Version Information) so it keeps
pressing Back until it actually reaches the main/Step-1 screen.

Run: .venv/bin/pytest tests/test_log_capture_returns_to_main_screen.py -v
"""
import src.log_capture as log_capture_mod


class _FakeInnerDriver:
    def activate_app(self, pkg):
        pass

    def press_keycode(self, code):
        pass


class _FakeDriver:
    """`screens` simulates what's visible after N Back presses -- index 0
    is the screen showing before any Back press, index 1 after the first
    Back press, etc. The last entry repeats once exhausted."""

    def __init__(self, screens):
        self.drv = _FakeInnerDriver()
        self.cfg = {"app_package": "com.wellysis.accurkardia.accurkardia.mobile"}
        self._screens = screens
        self._back_presses = 0

    def is_visible_text(self, texts, timeout=1, contains=True):
        idx = min(self._back_presses, len(self._screens) - 1)
        current = self._screens[idx]
        texts = [texts] if isinstance(texts, str) else texts
        return current in texts

    def tap_text(self, text, timeout=3, contains=False):
        pass

    def _press_back(self):
        self._back_presses += 1


def test_post_capture_backs_out_past_settings_to_main_screen(monkeypatch):
    """The exact bug: capture ends on "Version Information" -- the
    post-capture cleanup must not stop there, it must keep going until
    the real main screen is reached."""
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)
    drv = _FakeDriver(["Version Information", "Setting", "Log Symptoms"])
    monkeypatch.setattr(drv.drv, "press_keycode", lambda code: drv._press_back())

    log_capture_mod._ensure_menu_reachable(drv, target_screens=log_capture_mod._MAIN_SCREENS)

    assert drv._back_presses == 2, (
        "must press Back past both Version Information and Setting to reach "
        "Log Symptoms, not stop at the first Settings-family screen"
    )


def test_pre_capture_call_still_stops_at_settings(monkeypatch):
    """Negative-control-adjacent: the default (broad) target list used for
    the PRE-capture call must be unchanged -- Version Information is a
    perfectly good place to already be when heading INTO a capture."""
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)
    drv = _FakeDriver(["Version Information", "Setting", "Log Symptoms"])
    monkeypatch.setattr(drv.drv, "press_keycode", lambda code: drv._press_back())

    log_capture_mod._ensure_menu_reachable(drv)  # default target_screens

    assert drv._back_presses == 0, "the broad pre-capture list must accept Version Information immediately"
