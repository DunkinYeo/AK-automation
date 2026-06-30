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

    def _bt_is_actually_off() -> bool:
        """Verify BT actually turned off via dumpsys (svc/cmd may return 0 but not work)."""
        try:
            r = subprocess.run(adb + ["shell", "dumpsys", "bluetooth_manager"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                if "enabled:" in line:
                    return "false" in line.lower()
        except Exception:
            pass
        return False

    def _bt_disable() -> None:
        """Try multiple ADB commands to disable BT (Android version differences)."""
        cmds = [
            adb + ["shell", "svc", "bluetooth", "disable"],
            adb + ["shell", "cmd", "bluetooth_manager", "disable"],
        ]
        last_err = None
        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=10)
                if r.returncode == 0 and b"error" not in r.stderr.lower():
                    log.info("[bt_disconnect] BT disabled via: %s", " ".join(cmd[-3:]))
                    return
                last_err = r.stderr.decode(errors="replace").strip() or "non-zero exit"
            except Exception as e:
                last_err = str(e)
        raise RuntimeError(last_err or "all BT disable commands failed")

    try:
        _bt_disable()
    except Exception as e:
        log.warning("[bt_disconnect] disable failed: %s — waiting for ADB reconnect", e)
        if not driver.wait_for_adb_device(timeout=300):
            driver.reporter.log_event("bt_disconnect_failed", {"phase": "disable", "error": str(e)})
            return
        try:
            _bt_disable()
        except Exception as e2:
            driver.reporter.log_event("bt_disconnect_failed", {"phase": "disable", "error": str(e2)})
            return

    # Verify BT actually turned off — some devices (e.g. Samsung Android 11) accept
    # the ADB command but BT stays ON (returncode 0, no stderr, but state unchanged).
    time.sleep(2)
    if not _bt_is_actually_off():
        log.warning("[bt_disconnect] BT still ON after disable commands — ADB BT toggle not supported on this device/OS; skipping disconnect cycle")
        driver.reporter.log_event("bt_disconnect_not_supported", {
            "reason": "ADB BT toggle not effective on this device/OS (dumpsys confirms BT still ON)",
            "minutes": disconnect_minutes,
        })
        return

    # Give app time to detect BT loss, then run connectivity check to emit
    # bluetooth_off and trigger diary submission.
    time.sleep(5)
    try:
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[bt_disconnect] post-disable connectivity check failed: %s", _e)

    _wall_sleep(disconnect_minutes * 60 - 5)

    def _bt_enable() -> None:
        cmds = [
            adb + ["shell", "svc", "bluetooth", "enable"],
            adb + ["shell", "cmd", "bluetooth_manager", "enable"],
        ]
        last_err = None
        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=10)
                if r.returncode == 0 and b"error" not in r.stderr.lower():
                    log.info("[bt_disconnect] BT enabled via: %s", " ".join(cmd[-3:]))
                    return
                last_err = r.stderr.decode(errors="replace").strip() or "non-zero exit"
            except Exception as e:
                last_err = str(e)
        raise RuntimeError(last_err or "all BT enable commands failed")

    try:
        _bt_enable()
    except Exception as e:
        log.warning("[bt_disconnect] re-enable failed: %s — waiting for ADB reconnect", e)
        if not driver.wait_for_adb_device(timeout=300):
            driver.reporter.log_event("bt_disconnect_failed", {"phase": "enable", "error": str(e)})
            return
        try:
            _bt_enable()
        except Exception as e2:
            driver.reporter.log_event("bt_disconnect_failed", {"phase": "enable", "error": str(e2)})
            return

    driver.reporter.log_event("bt_disconnect_done", {"minutes": disconnect_minutes})
    log.info("[bt_disconnect] BT re-enabled after %.1f min", disconnect_minutes)

    # Run connectivity check after BT restores to emit bluetooth_reconnected.
    time.sleep(10)
    try:
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[bt_disconnect] post-enable connectivity check failed: %s", _e)
