"""
Run-end backstop: put the phone's radios back after a BT-off or airplane-mode
test that didn't finish (web Stop, crash, exception mid-window).

The BT / airplane workflows run in a daemon thread. Without this, stopping
the run while BT was off left the phone with BT off (or in airplane mode)
for whatever the tester did next (review 2026-11-05 #1).
"""
import logging
import subprocess
import time

log = logging.getLogger(__name__)


def pending(driver) -> set:
    """Radios a workflow has switched off and not yet confirmed restored:
    "bt" and/or "airplane". Kept on the driver so the run-end path sees it."""
    p = getattr(driver, "_conn_pending", None)
    if p is None:
        p = driver._conn_pending = set()
    return p


def _setting(adb: list, name: str) -> str:
    r = subprocess.run(adb + ["shell", "settings", "get", "global", name],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


def _wait_setting(adb: list, name: str, want: str, retries: int = 5, interval: float = 2.0) -> bool:
    for _ in range(retries):
        time.sleep(interval)
        try:
            if _setting(adb, name) == want:
                return True
        except Exception:
            pass
    return False


def ensure_bt_on(adb: list) -> bool:
    """Turn BT on if it isn't; True only once bluetooth_on reads exactly "1".
    An empty/failed read, "null" or "2" (off for airplane mode) is not "on"."""
    try:
        if _setting(adb, "bluetooth_on") == "1":
            return True
    except Exception:
        pass
    for cmd in (["svc", "bluetooth", "enable"], ["cmd", "bluetooth_manager", "enable"]):
        try:
            subprocess.run(adb + ["shell"] + cmd, capture_output=True, timeout=10)
        except Exception as e:
            log.warning("[conn_restore] %s failed: %s", " ".join(cmd), e)
        if _wait_setting(adb, "bluetooth_on", "1"):
            return True
    return False


def restore_connectivity(driver, reporter) -> None:
    """Undo whatever is still pending. ADB only — safe after the UI session
    is gone. Airplane mode can also take BT down, so BT is checked whenever
    anything was pending."""
    p = pending(driver)
    if not p:
        return
    udid = driver.cfg.get("udid", "")
    adb = ["adb"] + (["-s", udid] if udid else [])
    was = sorted(p)
    failed = []

    if "airplane" in p:
        try:
            subprocess.run(adb + ["shell", "cmd", "connectivity", "airplane-mode", "disable"],
                           capture_output=True, timeout=10)
        except Exception as e:
            log.warning("[conn_restore] airplane disable failed: %s", e)
        if _wait_setting(adb, "airplane_mode_on", "0"):
            p.discard("airplane")
        else:
            failed.append("airplane")

    bt_on = ensure_bt_on(adb)
    if bt_on:
        p.discard("bt")
    else:
        failed.append("bt")

    log.info("[conn_restore] pending %s → failed %s", was, failed)
    reporter.log_event("connectivity_restore_on_exit", {"pending": was, "failed": failed})
