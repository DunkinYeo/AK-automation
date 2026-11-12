"""
Airplane mode workflow: enable airplane mode, wait, disable.
Only runs when connected via USB — airplane mode cuts WiFi, which
would break a WiFi ADB session and make the device unreachable.
"""
import logging
import subprocess
import threading
import time

from src.driver import AndroidDriver
from src.workflows import conn_restore
from src.workflows.bt_disconnect import _wall_sleep

log = logging.getLogger(__name__)


def _is_usb(driver: AndroidDriver) -> bool:
    """Return True when ADB is over USB (udid has no colon, e.g. serial number)."""
    udid = driver.cfg.get("udid", "")
    return not (udid and ":" in udid and not udid.startswith("/"))


def _airplane_state_is(adb: list, want: str, retries: int = 5, interval: float = 2.0) -> bool:
    """Poll until airplane_mode_on == want (some devices apply the toggle late)."""
    return conn_restore._wait_setting(adb, "airplane_mode_on", want, retries, interval)


def _bt_back_on(adb: list) -> bool:
    """Some devices (e.g. Samsung Android 11) restore WiFi after airplane off
    but leave BT off. Re-enable it if needed; True once BT is confirmed on
    (bluetooth_on == "1" exactly — an empty read used to count as on)."""
    return conn_restore.ensure_bt_on(adb)


def run_airplane_mode(driver: AndroidDriver, airplane_minutes: float,
                      stop_event: threading.Event | None = None) -> None:
    """Enable airplane mode for `airplane_minutes`, then disable. USB-only.

    If `stop_event` is set during the airplane window (run stopping),
    airplane mode is turned off right away and the post-restore checks
    are skipped.
    """
    if not _is_usb(driver):
        log.info("[airplane_mode] Skipped — WiFi ADB (USB required)")
        driver.reporter.log_event("airplane_mode_skipped", {"reason": "wifi_adb"})
        return

    udid = driver.cfg.get("udid", "")
    adb = ["adb"] + (["-s", udid] if udid else [])

    pending = conn_restore.pending(driver)

    driver.reporter.log_event("airplane_mode_start", {"minutes": airplane_minutes})
    log.info("[airplane_mode] Enabling airplane mode for %.1f min", airplane_minutes)

    # Marked before the enable attempt: a command that "failed" may still
    # have switched airplane mode on, and the run-end restore must undo it.
    # BT too: airplane mode can take BT down, and some devices don't bring
    # it back when airplane mode turns off (review 2026-11-11 #1).
    pending.update({"airplane", "bt"})

    try:
        r = subprocess.run(adb + ["shell", "cmd", "connectivity", "airplane-mode", "enable"],
                           capture_output=True, timeout=10)
        if r.returncode != 0 or b"error" in r.stderr.lower():
            raise RuntimeError(r.stderr.decode(errors="replace").strip() or "non-zero exit")
    except Exception as e:
        log.warning("[airplane_mode] enable failed: %s — waiting for ADB reconnect", e)
        if not driver.wait_for_adb_device(timeout=300):
            driver.reporter.log_event("airplane_mode_failed", {"phase": "enable", "error": str(e)})
            return
        try:
            r = subprocess.run(adb + ["shell", "cmd", "connectivity", "airplane-mode", "enable"],
                               capture_output=True, timeout=10)
            if r.returncode != 0 or b"error" in r.stderr.lower():
                raise RuntimeError(r.stderr.decode(errors="replace").strip() or "non-zero exit")
        except Exception as e2:
            driver.reporter.log_event("airplane_mode_failed", {"phase": "enable", "error": str(e2)})
            return

    # A zero exit doesn't mean the setting changed; without this the test
    # waited with the radios still up and logged airplane_mode_done
    # (review 2026-11-11 #2).
    if not _airplane_state_is(adb, "1"):
        log.warning("[airplane_mode] Airplane mode did not turn on after enable command")
        driver.reporter.log_event("airplane_mode_failed", {
            "phase": "enable", "minutes": airplane_minutes,
            "error": "airplane mode did not turn on after enable command",
        })
        # In case it turns on late: switch it back off and check BT.
        try:
            subprocess.run(adb + ["shell", "cmd", "connectivity", "airplane-mode", "disable"],
                           capture_output=True, timeout=10)
        except Exception as e:
            log.warning("[airplane_mode] disable after failed enable: %s", e)
        if _airplane_state_is(adb, "0"):
            pending.discard("airplane")
            if _bt_back_on(adb):
                pending.discard("bt")
        return

    # Give WiFi time to drop, then run connectivity check to detect wifi_off
    # and trigger diary submission. Background monitor is paused during airplane mode.
    time.sleep(3)
    try:
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[airplane_mode] post-enable connectivity check failed: %s", _e)

    stopped = _wall_sleep(airplane_minutes * 60 - 3, stop_event)
    if stopped:
        log.info("[airplane_mode] Run stopping — turning airplane mode off early")

    try:
        r = subprocess.run(adb + ["shell", "cmd", "connectivity", "airplane-mode", "disable"],
                           capture_output=True, timeout=10)
        if r.returncode != 0 or b"error" in r.stderr.lower():
            raise RuntimeError(r.stderr.decode(errors="replace").strip() or "non-zero exit")
    except Exception as e:
        log.warning("[airplane_mode] disable failed: %s — waiting for ADB reconnect", e)
        if not driver.wait_for_adb_device(timeout=300):
            driver.reporter.log_event("airplane_mode_failed", {"phase": "disable", "error": str(e)})
            return
        try:
            r = subprocess.run(adb + ["shell", "cmd", "connectivity", "airplane-mode", "disable"],
                               capture_output=True, timeout=10)
            if r.returncode != 0 or b"error" in r.stderr.lower():
                raise RuntimeError(r.stderr.decode(errors="replace").strip() or "non-zero exit")
        except Exception as e2:
            driver.reporter.log_event("airplane_mode_failed", {"phase": "disable", "error": str(e2)})
            return

    if not _airplane_state_is(adb, "0"):
        log.warning("[airplane_mode] Airplane mode still ON after disable command")
        driver.reporter.log_event("airplane_mode_failed", {
            "phase": "restore", "minutes": airplane_minutes,
            "error": "airplane mode still on after disable command",
        })
        return
    pending.discard("airplane")

    # Checked before done/aborted is logged: a cycle that leaves BT off is a
    # failure, and "bt" stays pending so the run-end restore tries again.
    time.sleep(3)
    if not _bt_back_on(adb):
        log.warning("[airplane_mode] BT could not be re-enabled after airplane mode")
        driver.reporter.log_event("airplane_mode_failed", {
            "phase": "restore", "minutes": airplane_minutes,
            "error": "Bluetooth still off after airplane mode off",
        })
        return
    pending.discard("bt")

    if stopped:
        # Post-restore UI checks skipped: the run is stopping.
        driver.reporter.log_event("airplane_mode_aborted", {"minutes": airplane_minutes})
        return

    driver.reporter.log_event("airplane_mode_done", {"minutes": airplane_minutes})
    log.info("[airplane_mode] Airplane mode disabled after %.1f min", airplane_minutes)

    # Run connectivity check after WiFi restores to emit wifi_off_resolved / wifi_restored.
    time.sleep(2)
    try:
        driver.ensure_session()
        driver.ensure_ui_automation()
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[airplane_mode] post-disable connectivity check failed: %s", _e)
        try:
            driver.reconnect()
            driver.check_connectivity()
        except Exception as _e2:
            log.warning("[airplane_mode] post-disable connectivity retry failed: %s", _e2)
