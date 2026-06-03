"""
Airplane mode workflow: enable airplane mode, wait, disable.
Only runs when connected via USB — airplane mode cuts WiFi, which
would break a WiFi ADB session and make the device unreachable.
"""
import logging
import subprocess
import time

from src.driver import AndroidDriver

_TICK = 5  # seconds per poll tick


def _wall_sleep(seconds: float) -> None:
    """Sleep for `seconds` of wall-clock time, robust to host sleep/wake."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_TICK, remaining))

log = logging.getLogger(__name__)


def _is_usb(driver: AndroidDriver) -> bool:
    """Return True when ADB is over USB (udid has no colon, e.g. serial number)."""
    udid = driver.cfg.get("udid", "")
    return not (udid and ":" in udid and not udid.startswith("/"))


def run_airplane_mode(driver: AndroidDriver, airplane_minutes: float) -> None:
    """Enable airplane mode for `airplane_minutes`, then disable. USB-only."""
    if not _is_usb(driver):
        log.info("[airplane_mode] Skipped — WiFi ADB (USB required)")
        driver.reporter.log_event("airplane_mode_skipped", {"reason": "wifi_adb"})
        return

    udid = driver.cfg.get("udid", "")
    adb = ["adb"] + (["-s", udid] if udid else [])

    driver.reporter.log_event("airplane_mode_start", {"minutes": airplane_minutes})
    log.info("[airplane_mode] Enabling airplane mode for %.1f min", airplane_minutes)

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

    # Give WiFi time to drop, then run connectivity check to detect wifi_off
    # and trigger diary submission. Background monitor is paused during airplane mode.
    time.sleep(3)
    try:
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[airplane_mode] post-enable connectivity check failed: %s", _e)

    _wall_sleep(airplane_minutes * 60 - 3)

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

    driver.reporter.log_event("airplane_mode_done", {"minutes": airplane_minutes})
    log.info("[airplane_mode] Airplane mode disabled after %.1f min", airplane_minutes)

    # Run connectivity check after WiFi restores to emit wifi_off_resolved / wifi_restored.
    time.sleep(5)
    try:
        driver.check_connectivity()
    except Exception as _e:
        log.warning("[airplane_mode] post-disable connectivity check failed: %s", _e)
