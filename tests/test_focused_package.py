"""
Regression test: the foreground-app check must read `dumpsys window`, not
`dumpsys window windows`.

Found 2026-11-12: on Android 11 (Galaxy A32) and 16 (Pixel 7)
`dumpsys window windows` has no mCurrentFocus line, so the check always
returned "" and dismiss_unexpected_popups() never acted on a system popup.

Run: .venv/bin/pytest tests/test_focused_package.py -v
"""
import types

from src.driver import AndroidDriver

_DUMP = """WINDOW MANAGER WINDOWS (dumpsys window windows)
  mCurrentFocus=Window{68e9cf9 u0 com.example.app/com.example.app.MainActivity}
  mFocusedApp=ActivityRecord{65697617 u0 com.example.app/.MainActivity t1834}
"""


def test_focused_package_reads_full_window_dump(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        # Only the full dump carries mCurrentFocus on current Android
        return types.SimpleNamespace(stdout=_DUMP if cmd[-1] == "window" else "")
    monkeypatch.setattr("src.driver.subprocess.run", run)
    d = AndroidDriver.__new__(AndroidDriver)
    d.cfg = {"udid": "SER"}

    assert d._adb_focused_package() == "com.example.app"
    assert calls[0][-2:] == ["dumpsys", "window"]
