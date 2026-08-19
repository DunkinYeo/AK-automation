"""
Regression tests for the start_activity() Appium-Python-Client 4.0+
compatibility fix (src/driver.py, src/regression/helpers.py).

Real failure caught live, 2026-08-19: Appium-Python-Client 4.0.0 (the
version actually installed) removed the old start_activity() JSONWP
shortcut entirely. Three call sites still used it as a last-resort
fallback after activate_app() failed:

  - AndroidDriver.bring_to_foreground() -- already wrapped in its own
    try/except: pass, so this one degraded silently.
  - AndroidDriver.recover_session(step=3) -- NOT wrapped at that specific
    line; the AttributeError propagated up through the outer
    try/except's re-raise and crashed the whole run
    ("'WebDriver' object has no attribute 'start_activity'",
    run_failed, ~9s after run_start on a real device).
    - src.regression.helpers.reset_to_step1(hard=True) -- also
    unwrapped at that line, same crash risk.

Fix: all three now go through AndroidDriver._start_activity_compat(),
which uses the documented UiAutomator2 replacement
(execute_script("mobile: startActivity", ...)) and never raises.

Run: .venv/bin/pytest tests/test_start_activity_compat.py -v
"""
import src.driver as driver_mod
from src.regression import helpers as helpers_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


class _FakeInnerDriver:
    def __init__(self, activate_app_raises=False, execute_script_raises=False):
        self.activate_app_raises = activate_app_raises
        self.execute_script_raises = execute_script_raises
        self.calls = []

    def terminate_app(self, pkg):
        self.calls.append(("terminate_app", pkg))

    def activate_app(self, pkg):
        self.calls.append(("activate_app", pkg))
        if self.activate_app_raises:
            raise RuntimeError("app not resumable")

    def execute_script(self, name, args):
        self.calls.append(("execute_script", name, args))
        if self.execute_script_raises:
            raise RuntimeError("mobile: startActivity not supported")

    def press_keycode(self, code):
        pass


def _make_driver(activate_app_raises=True, execute_script_raises=False):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"app_package": "com.wellysis.accurkardia.accurkardia.mobile",
               "app_activity": "com.wellysis.accurkardia.accurkardia.mobile.MainActivity"}
    drv.reporter = _FakeReporter()
    drv.drv = _FakeInnerDriver(activate_app_raises=activate_app_raises,
                                execute_script_raises=execute_script_raises)
    return drv


def test_start_activity_compat_uses_mobile_command():
    drv = _make_driver()
    drv._start_activity_compat("pkg.name", ".MainActivity")
    assert ("execute_script", "mobile: startActivity",
            {"appPackage": "pkg.name", "appActivity": ".MainActivity"}) in drv.drv.calls


def test_start_activity_compat_never_raises():
    """Even if the modern replacement itself fails, this must stay silent
    -- it's only ever a last-resort fallback."""
    drv = _make_driver(execute_script_raises=True)
    drv._start_activity_compat("pkg.name", ".MainActivity")  # must not raise


def test_recover_session_step3_does_not_crash_when_activate_app_fails(monkeypatch):
    """The exact live bug: activate_app() failing inside recover_session's
    step 3 used to fall through to the removed start_activity() and crash
    the whole run with an unhandled AttributeError. Must now recover
    cleanly via the compat shim and still report success."""
    monkeypatch.setattr(driver_mod.time, "sleep", lambda *_: None)
    drv = _make_driver(activate_app_raises=True)
    monkeypatch.setattr(drv, "ensure_screen_on", lambda: None)
    monkeypatch.setattr(drv, "wait_idle", lambda *_: None)

    result = drv.recover_session(step=3)

    assert result is True
    assert ("execute_script", "mobile: startActivity",
            {"appPackage": drv.cfg["app_package"], "appActivity": drv.cfg["app_activity"]}) in drv.drv.calls
    assert not any(name == "recovery_failed" for name, _ in drv.reporter.events)


def test_reset_to_step1_hard_does_not_crash_when_activate_app_fails(monkeypatch):
    """Same class of bug, the helpers.py call site."""
    monkeypatch.setattr(helpers_mod.time, "sleep", lambda *_: None)
    drv = _make_driver(activate_app_raises=True)

    helpers_mod.reset_to_step1(drv, hard=True)  # must not raise

    assert ("execute_script", "mobile: startActivity",
            {"appPackage": drv.cfg["app_package"], "appActivity": drv.cfg["app_activity"]}) in drv.drv.calls
