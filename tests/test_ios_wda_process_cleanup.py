"""
Regression tests for issue #40: IOSDriver's WDA/iproxy processes were
fire-and-forget (never tracked), so a reconnect had no way to reliably
kill the exact process it had previously started — pattern-matched pkill
plus a fixed sleep(0.5) wasn't enough, and a real 19h run hit "port #8100
is occupied by an other process" 41 times, including 2 full recovery
failures that silently dropped a job each (#39).

Run: .venv/bin/pytest tests/test_ios_wda_process_cleanup.py -v
"""
import socket
import subprocess
import sys
import time
from unittest import mock

from src.driver_ios import IOSDriver


def _make_driver():
    """IOSDriver.__init__ opens a real Appium session — for these tests we
    only need the instance attributes/methods under test, not a live
    connection."""
    return IOSDriver.__new__(IOSDriver)


def test_port_is_free_detects_bound_port():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert IOSDriver._port_is_free(port) is False
    finally:
        srv.close()
    # Give the OS a brief moment to release the socket, then confirm free.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not IOSDriver._port_is_free(port):
        time.sleep(0.05)
    assert IOSDriver._port_is_free(port) is True


def test_kill_tracked_wda_procs_kills_real_running_process():
    drv = _make_driver()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    drv._wda_proc = proc
    drv._iproxy_proc = None
    try:
        assert proc.poll() is None  # still running
        drv._kill_tracked_wda_procs()
        assert proc.poll() is not None, "process should be dead after cleanup"
        assert drv._wda_proc is None
        assert drv._iproxy_proc is None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_kill_tracked_wda_procs_handles_already_dead_process():
    """Negative-control-adjacent: a process that already exited on its own
    (e.g. crashed) must not raise — and the attribute must still be reset."""
    drv = _make_driver()
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()  # already exited
    drv._wda_proc = proc
    drv._iproxy_proc = None

    drv._kill_tracked_wda_procs()  # must not raise
    assert drv._wda_proc is None


def test_kill_tracked_wda_procs_noop_when_nothing_tracked():
    drv = _make_driver()
    drv._wda_proc = None
    drv._iproxy_proc = None
    drv._kill_tracked_wda_procs()  # must not raise
    assert drv._wda_proc is None
    assert drv._iproxy_proc is None


def test_xcodebuild_fallback_cleans_up_pymobiledevice3_leftovers():
    """Code review finding (2026-07-31): if _start_wda_via_pymobiledevice3
    starts iproxy/WDA but then fails the 60s readiness poll (returns
    False), _build_options() falls back to Appium's own xcodebuild-launched
    WDA — which tries to bind the same wda_port. Without cleaning up first,
    the still-alive pymobiledevice3 WDA/iproxy would conflict with it."""
    drv = _make_driver()
    drv.cfg = {"wda_local_port": 8100, "device_name": "iPhone", "platform_version": "18.6",
               "udid": "", "bundle_id": "", "no_reset": True, "new_command_timeout": 3600}

    with mock.patch.object(drv, "_wda_is_running", return_value=False), \
         mock.patch.object(drv, "_start_wda_via_pymobiledevice3", return_value=False), \
         mock.patch.object(drv, "_kill_tracked_wda_procs") as kill_mock:
        drv._build_options()
        kill_mock.assert_called_once()
