"""
BT disconnect workflow: disable BT, wait, re-enable.
Simulates the S-Patch moving out of Bluetooth range.
"""
import logging
import subprocess
import threading
import time

from src.driver import AndroidDriver

log = logging.getLogger(__name__)

# Use a threading.Event for the sleep so wall-clock time is used even when
# the host Mac wakes from sleep (time.sleep is paused during system sleep).
_TICK = 5  # seconds per poll tick during the wait


def _wall_sleep(seconds: float) -> None:
    """Sleep for `seconds` of wall-clock time, robust to host sleep/wake."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_TICK, remaining))


def run_bt_disconnect(driver: AndroidDriver, disconnect_minutes: float) -> None:
    """Disable Bluetooth for `disconnect_minutes`, then re-enable."""
    udid = driver.cfg.get("udid", "")
    adb = ["adb"] + (["-s", udid] if udid else [])

    driver.reporter.log_event("bt_disconnect_start", {"minutes": disconnect_minutes})
    log.info("[bt_disconnect] Disabling BT for %.1f min", disconnect_minutes)

    try:
        subprocess.run(adb + ["shell", "svc", "bluetooth", "disable"],
                       capture_output=True, timeout=10)
    except Exception as e:
        log.warning("[bt_disconnect] disable failed: %s", e)
        driver.reporter.log_event("bt_disconnect_failed", {"phase": "disable", "error": str(e)})
        return

    # Give app time to detect BT loss, then run connectivity check to emit
    # bluetooth_off and trigger diary submission.
    time.sleep(5)
    try:
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[bt_disconnect] post-disable connectivity check failed: %s", _e)

    _wall_sleep(disconnect_minutes * 60 - 5)

    try:
        subprocess.run(adb + ["shell", "svc", "bluetooth", "enable"],
                       capture_output=True, timeout=10)
    except Exception as e:
        log.warning("[bt_disconnect] re-enable failed: %s", e)
        driver.reporter.log_event("bt_disconnect_failed", {"phase": "enable", "error": str(e)})
        return

    driver.reporter.log_event("bt_disconnect_done", {"minutes": disconnect_minutes})
    log.info("[bt_disconnect] BT re-enabled after %.1f min", disconnect_minutes)

    # Run connectivity check after BT restores to emit bluetooth_reconnected.
    time.sleep(10)
    try:
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[bt_disconnect] post-enable connectivity check failed: %s", _e)
