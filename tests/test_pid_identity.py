"""
Regression tests for web.app._pid_is_our_run() — issues #20/#28/#31/#32.

This function gates real destructive/state-changing decisions (re-attach
after a server restart, /api/stop sending a kill signal, Inject Now,
_kill_proc's screen-timeout backstop skip — issues #16/#20/#30/#33), so a
silent regression here is exactly the class of bug that's easy to
reintroduce without noticing:
  - #28: `ps` doesn't exist on Windows -> the check must use a Windows
    path (PowerShell Get-CimInstance) instead of silently degrading to
    alive-only.
  - #31: Windows CommandLine uses backslashes; matching only "src/main.py"
    (forward slash) would make a real Windows run fail its own check.
  - #32: on any verification failure, the fallback must be False (fail
    closed) — not True, which would defeat #20/#28's entire purpose for
    the one call site that actually sends a kill signal.
  - latest review round (2026-07-29): matching a bare "src/main.py"
    substring anywhere in the command line matched ANY project with a
    src/main.py anywhere in its path (e.g. an unrelated /tmp/foo/src/main.py)
    — exactly the false-positive #20/#28 exist to prevent. The fix compares
    against this installation's actual ROOT/src/main.py path, so these tests
    patch app_mod.ROOT to the temp dir under test rather than relying on
    a loose substring match.

Run: .venv/bin/pytest tests/test_pid_identity.py -v
"""
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from unittest import mock

import web.app as app_mod


def _spawn(root: Path, *, as_main_py: bool):
    """Start a real short-lived subprocess. If as_main_py, its command line
    contains a real ".../src/main.py" path segment under `root` (mirrors how
    api_start actually spawns a run: cmd = [sys.executable, str(ROOT/"src"/entry), ...]) —
    otherwise it's a same-interpreter process with an unrelated script name,
    i.e. a stand-in for "the OS reused this pid for something else"."""
    if as_main_py:
        script_dir = root / "src"
        script_dir.mkdir(exist_ok=True)
        script = script_dir / "main.py"
    else:
        script = root / "unrelated.py"
    script.write_text("import time; time.sleep(5)\n")
    return subprocess.Popen([sys.executable, str(script)])


def test_real_process_matching_our_root_is_recognized(tmp_path):
    """A process spawned from this installation's own ROOT/src/main.py must
    be recognized as ours."""
    proc = _spawn(tmp_path, as_main_py=True)
    try:
        with mock.patch.object(app_mod, "ROOT", tmp_path):
            assert app_mod._pid_is_our_run(proc.pid) is True
    finally:
        proc.kill()
        proc.wait()


def test_real_unrelated_process_is_rejected(tmp_path):
    proc = _spawn(tmp_path, as_main_py=False)
    try:
        with mock.patch.object(app_mod, "ROOT", tmp_path):
            assert app_mod._pid_is_our_run(proc.pid) is False
    finally:
        proc.kill()
        proc.wait()


def test_real_process_from_different_project_src_main_py_is_rejected(tmp_path):
    """Regression for the loose-substring bug: a genuinely different
    installation's own src/main.py (same relative path, different ROOT)
    must NOT be recognized as ours — only an exact match against *this*
    installation's ROOT counts."""
    other_root = tmp_path / "unrelated_project"
    other_root.mkdir()
    proc = _spawn(other_root, as_main_py=True)
    try:
        # app_mod.ROOT stays as the real ROOT here — deliberately not patched
        # to other_root, so this exercises the actual production comparison.
        assert app_mod._pid_is_our_run(proc.pid) is False
    finally:
        proc.kill()
        proc.wait()


def test_dead_pid_is_rejected():
    proc = subprocess.Popen(["true"] if sys.platform != "win32" else ["cmd", "/c", "exit"])
    proc.wait()
    assert app_mod._pid_alive(proc.pid) is False
    assert app_mod._pid_is_our_run(proc.pid) is False


def test_windows_backslash_command_line_is_matched():
    """#31: Windows CommandLine comes back with backslashes — the real
    spawn command (via pathlib on Windows) does too, so a genuinely-correct
    Windows run must not fail its own identity check. Uses a patched ROOT
    (PureWindowsPath, since the real ROOT on the dev/CI machine running this
    test is a PosixPath regardless of the sys.platform mock) so the fake
    CommandLine is built from — and exact-matched against — the same ROOT
    the function under test actually compares against."""
    fake_root = PureWindowsPath("C:\\Users\\tester\\AK-automation")
    main_py = str(fake_root / "src" / "main.py")

    class _FakeProc:
        def communicate(self, timeout=None):
            return (f'"C:\\Python313\\python.exe" "{main_py}" '
                    f'--config "{fake_root}\\config\\_web_run.yaml"\r\n', "")
        def kill(self): pass
        def wait(self, timeout=None): pass

    with mock.patch.object(app_mod, "_pid_alive", return_value=True), \
         mock.patch.object(app_mod, "ROOT", fake_root), \
         mock.patch.object(app_mod.sys, "platform", "win32"), \
         mock.patch.object(app_mod.subprocess, "Popen", return_value=_FakeProc()):
        assert app_mod._pid_is_our_run(1234) is True


def test_windows_unrelated_process_is_rejected():
    fake_root = PureWindowsPath("C:\\Users\\tester\\AK-automation")

    class _FakeProc:
        def communicate(self, timeout=None):
            return ('"C:\\Windows\\System32\\notepad.exe"\r\n', "")
        def kill(self): pass
        def wait(self, timeout=None): pass

    with mock.patch.object(app_mod, "_pid_alive", return_value=True), \
         mock.patch.object(app_mod, "ROOT", fake_root), \
         mock.patch.object(app_mod.sys, "platform", "win32"), \
         mock.patch.object(app_mod.subprocess, "Popen", return_value=_FakeProc()):
        assert app_mod._pid_is_our_run(5678) is False


def test_windows_different_installation_src_main_py_is_rejected():
    """Same regression as test_real_process_from_different_project_src_main_py_is_rejected,
    but for the Windows CommandLine path: another AK-automation checkout at a
    different location (e.g. a co-worker's path, or a leftover clone) must
    not be recognized as *this* installation just because the relative
    src/main.py suffix matches."""
    fake_root = PureWindowsPath("C:\\Users\\tester\\AK-automation")
    other_root = PureWindowsPath("C:\\Users\\tester\\Desktop\\old-AK-automation-copy")
    other_main_py = str(other_root / "src" / "main.py")

    class _FakeProc:
        def communicate(self, timeout=None):
            return (f'"C:\\Python313\\python.exe" "{other_main_py}"\r\n', "")
        def kill(self): pass
        def wait(self, timeout=None): pass

    with mock.patch.object(app_mod, "_pid_alive", return_value=True), \
         mock.patch.object(app_mod, "ROOT", fake_root), \
         mock.patch.object(app_mod.sys, "platform", "win32"), \
         mock.patch.object(app_mod.subprocess, "Popen", return_value=_FakeProc()):
        assert app_mod._pid_is_our_run(4321) is False


def test_verification_failure_fails_closed_not_open():
    """#32: a verification error (subprocess hiccup, or the real
    KeyboardInterrupt reproduced live on windows-latest under GitHub
    Actions' pwsh wrapper, 2026-07-29) must return False, never True —
    this function's whole point is gating /api/stop's kill signal, and
    "couldn't verify" is not the same as "confirmed ours"."""
    class _ExplodingProc:
        def communicate(self, timeout=None):
            raise KeyboardInterrupt("simulated hiccup")
        def kill(self): pass
        def wait(self, timeout=None): pass

    with mock.patch.object(app_mod, "_pid_alive", return_value=True), \
         mock.patch.object(app_mod.subprocess, "Popen", return_value=_ExplodingProc()):
        assert app_mod._pid_is_our_run(9999) is False
