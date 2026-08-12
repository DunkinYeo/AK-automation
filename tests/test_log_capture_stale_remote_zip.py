"""
Regression test for capture_app_logs()'s handling of a stale remote zip
left over from an earlier capture (code review finding, 2026-08-12,
confirmed against real live data: two captures of the same run 4.5h
apart both produced /sdcard/Download/<same-uuid>.zip, since the app
re-exports the same study/session to the same UUID filename every time).

Before the fix: _wait_for_stable_file() only checks that the remote
file's size is unchanged across two consecutive polls. If a stale file
from a previous capture is already sitting at that path when a new
Download is tapped, its already-stable size can pass the check before
the new export has even started writing -- silently pulling stale data.

Fix: best-effort `adb shell rm -f <remote_path>` right before tapping
Download, so the stability check can only ever observe the fresh file.
This test verifies that delete happens, with the correct path, before
the Download tap -- using a fully mocked driver/subprocess (no real
device needed).

Run: .venv/bin/pytest tests/test_log_capture_stale_remote_zip.py -v
"""
from pathlib import Path

import src.log_capture as log_capture_mod

_UUID = "063addda-61fc-4907-a1c7-86a47ca1ce67"
_PAGE_SRC = f'<hierarchy>text="File Information" text="{_UUID}"</hierarchy>'


class _FakeElement:
    location = {"x": 100, "y": 200}
    size = {"width": 50, "height": 20}


class _FakeInnerDriver:
    page_source = _PAGE_SRC

    def tap(self, points):
        pass


class _FakeDriver:
    def __init__(self, calls):
        self._calls = calls
        self.drv = _FakeInnerDriver()

    def find(self, value, timeout=10, contains=False):
        assert value == "Current Version"
        return _FakeElement()

    def tap_text(self, text, timeout=10):
        self._calls.append(("tap_text", text))

    def _adb_cmd(self):
        return ["adb"]


def _make_fake_subprocess_run(calls, local_out: dict):
    def fake_run(cmd, **kwargs):
        calls.append(("subprocess", tuple(cmd)))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        r = _Result()
        if "rm" in cmd:
            pass
        elif "stat" in cmd:
            r.stdout = "12345"  # stable non-zero size on every poll
        elif "pull" in cmd:
            remote_path, local_path = cmd[-2], cmd[-1]
            Path(local_path).write_bytes(b"fake zip contents")
            local_out["remote_path"] = remote_path
        return r
    return fake_run


def test_stale_remote_zip_deleted_before_download_tap(tmp_path, monkeypatch):
    monkeypatch.setattr(log_capture_mod, "_ensure_menu_reachable", lambda drv: None)
    monkeypatch.setattr(log_capture_mod, "open_menu", lambda drv: None)
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)

    calls = []
    local_out = {}
    monkeypatch.setattr(
        log_capture_mod.subprocess, "run", _make_fake_subprocess_run(calls, local_out)
    )

    drv = _FakeDriver(calls)
    result_path = log_capture_mod._capture_app_logs_inner(drv, tmp_path, timeout=30)

    assert result_path.name == f"{_UUID}.zip"
    assert local_out["remote_path"] == f"/sdcard/Download/{_UUID}.zip"

    # Find the rm call and the Download tap in the recorded order.
    rm_index = next(
        i for i, c in enumerate(calls)
        if c[0] == "subprocess" and "rm" in c[1] and f"/sdcard/Download/{_UUID}.zip" in c[1]
    )
    download_tap_index = next(
        i for i, c in enumerate(calls) if c == ("tap_text", "Download")
    )
    assert rm_index < download_tap_index, (
        "the stale remote zip must be deleted before Download is tapped, "
        "otherwise _wait_for_stable_file can pass on the leftover file"
    )


def test_no_stale_zip_case_still_succeeds(tmp_path, monkeypatch):
    """Negative-control-adjacent: the delete is best-effort (rm -f on a
    nonexistent file) and must not break the normal no-stale-file case."""
    monkeypatch.setattr(log_capture_mod, "_ensure_menu_reachable", lambda drv: None)
    monkeypatch.setattr(log_capture_mod, "open_menu", lambda drv: None)
    monkeypatch.setattr(log_capture_mod.time, "sleep", lambda *_: None)

    calls = []
    local_out = {}
    monkeypatch.setattr(
        log_capture_mod.subprocess, "run", _make_fake_subprocess_run(calls, local_out)
    )

    drv = _FakeDriver(calls)
    result_path = log_capture_mod._capture_app_logs_inner(drv, tmp_path, timeout=30)
    assert result_path.exists()
