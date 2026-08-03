"""
Regression tests for issue #34: Appium webdriver HTTP calls had no
client-side timeout, so a stalled Appium/adb/WDA connection could block a
job forever while holding job_lock — deadlocking the scheduler's shutdown
(sched.shutdown(wait=True) waits on that same stuck worker thread) and
silently hanging the whole run with no run_complete/run_failed ever logged.

Real incident: output/20260728_112218 (pid 46264) hung for 21+ hours after
study completion, confirmed via macOS `sample` thread dump showing the
worker thread blocked in a socket recv() with no timeout.

Run: .venv/bin/pytest tests/test_appium_http_timeout.py -v
"""
import socket
import threading
import time
from unittest import mock

import pytest
import urllib3
from selenium.webdriver.remote.remote_connection import RemoteConnection

import src.driver as driver_mod
import src.driver_ios as driver_ios_mod


def _make_driver(cls, module, cfg):
    """Build a driver instance without running the real __init__ (which
    would try to open a real Appium session) — only _connect() is under
    test. _build_options() is also mocked: IOSDriver's real implementation
    calls _start_wda_via_pymobiledevice3(), which — if a real iPhone
    happens to be plugged in — spawns real iproxy/WDA subprocesses and
    waits up to 60s for readiness (discovered when this test suite
    started taking 2+ minutes locally with a device connected; these are
    supposed to be hardware-free unit tests, matching every other test in
    this file and this project's "no device/Appium needed" convention)."""
    inst = cls.__new__(cls)
    inst.cfg = cfg
    inst.reporter = mock.Mock()
    with mock.patch.object(module, "webdriver") as fake_webdriver, \
         mock.patch.object(cls, "_build_options", return_value=mock.Mock()):
        fake_webdriver.Remote.return_value = mock.Mock()
        inst._connect()
    return fake_webdriver.Remote


def test_android_connect_sets_default_timeout():
    with mock.patch.object(driver_mod.RemoteConnection, "set_timeout") as set_timeout:
        _make_driver(driver_mod.AndroidDriver, driver_mod, {})
        set_timeout.assert_called_once_with(120)


def test_android_connect_honors_configured_timeout():
    with mock.patch.object(driver_mod.RemoteConnection, "set_timeout") as set_timeout:
        _make_driver(driver_mod.AndroidDriver, driver_mod, {"appium_http_timeout": 45})
        set_timeout.assert_called_once_with(45)


def test_ios_connect_sets_default_timeout():
    with mock.patch.object(driver_ios_mod.RemoteConnection, "set_timeout") as set_timeout:
        _make_driver(driver_ios_mod.IOSDriver, driver_ios_mod, {})
        set_timeout.assert_called_once_with(120)


def test_ios_connect_honors_configured_timeout():
    with mock.patch.object(driver_ios_mod.RemoteConnection, "set_timeout") as set_timeout:
        _make_driver(driver_ios_mod.IOSDriver, driver_ios_mod, {"appium_http_timeout": 45})
        set_timeout.assert_called_once_with(45)


@pytest.fixture
def hung_server():
    """A real TCP server that accepts connections and then never responds —
    stands in for a stalled Appium server / dropped adb-forward tunnel."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def accept_and_hang():
        srv.settimeout(1.0)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            # Accept the connection but never send a reply — this is the
            # exact "hung Appium/WDA" scenario. Hold it open until the test
            # tears down, then close.
            while not stop.is_set():
                time.sleep(0.05)
            conn.close()

    t = threading.Thread(target=accept_and_hang, daemon=True)
    t.start()
    try:
        yield port
    finally:
        stop.set()
        srv.close()
        t.join(timeout=2)


def test_negative_control_no_timeout_would_hang(hung_server):
    """Without a timeout configured (the pre-fix state), a request to a
    server that accepts-but-never-responds blocks far longer than any
    reasonable request should take. We can't literally wait forever in a
    test, so this proves the hang is real by confirming the request is
    still not done after a short grace window with no timeout set —
    establishing the negative control that test_timeout_actually_aborts_
    a_stalled_request below is actually exercising a real fix, not a no-op."""
    RemoteConnection.reset_timeout()
    pool = urllib3.PoolManager(timeout=RemoteConnection.get_timeout())
    done = threading.Event()

    def make_request():
        try:
            pool.request("GET", f"http://127.0.0.1:{hung_server}/", retries=False)
        except Exception:
            pass
        finally:
            done.set()

    t = threading.Thread(target=make_request, daemon=True)
    t.start()
    finished_early = done.wait(timeout=3)
    assert finished_early is False, (
        "request unexpectedly returned without a client timeout — "
        "negative control invalid, can't trust the positive case below"
    )
    # Don't leak the thread past the test — hung_server's teardown will
    # release the connection, letting this eventually unblock.


def test_timeout_actually_aborts_a_stalled_request(hung_server):
    """The actual fix: with RemoteConnection.set_timeout() configured (as
    _connect() now does), a request to the same hung server fails fast
    instead of hanging forever."""
    RemoteConnection.set_timeout(2)
    try:
        pool = urllib3.PoolManager(timeout=RemoteConnection.get_timeout())
        start = time.monotonic()
        with pytest.raises(Exception):
            pool.request("GET", f"http://127.0.0.1:{hung_server}/", retries=False)
        elapsed = time.monotonic() - start
        assert elapsed < 10, f"request took {elapsed}s — timeout did not apply"
    finally:
        RemoteConnection.reset_timeout()
