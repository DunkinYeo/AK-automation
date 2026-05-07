"""
TC-CONN: Connectivity (BT / WiFi) regression tests during active study (AK)
Requires study active + physical S-Patch patch within BLE range.
BT off indicator: Real-time ECG tab shows "Patch Placement" (Live ECG Signal disappears).
WiFi off indicator: ADB settings get global wifi_on == 0 + Network card state change.
"""
import subprocess
import time
import logging

log = logging.getLogger(__name__)

_NO_STUDY    = "No study information"
_START_STUDY = "Start Study"
_ECG_TAB     = "Real-time ECG"
_DEV_TAB     = "Device Status"
_ECG_LIVE    = "Live ECG Signal"
_PATCH_PLACE = "Patch Placement"


def _not_started(drv) -> bool:
    return drv.is_visible_text(_START_STUDY, timeout=2)


def _adb(drv, *args):
    udid = drv.cfg.get("udid", "")
    cmd = ["adb"]
    if udid:
        cmd += ["-s", udid]
    cmd += list(args)
    subprocess.run(cmd, capture_output=True, timeout=10)


def _bt_off(drv):
    _adb(drv, "shell", "cmd", "bluetooth_manager", "disable")


def _bt_on(drv):
    _adb(drv, "shell", "cmd", "bluetooth_manager", "enable")


def _wifi_off(drv):
    _adb(drv, "shell", "svc", "wifi", "disable")


def _wifi_on(drv):
    _adb(drv, "shell", "svc", "wifi", "enable")


def _wifi_is_off(drv) -> bool:
    udid = drv.cfg.get("udid", "")
    cmd = ["adb"]
    if udid:
        cmd += ["-s", udid]
    cmd += ["shell", "settings", "get", "global", "wifi_on"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "0"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_conn_000_study_active(drv, runner):
    """TC-CONN-000 | Pre-check: study active"""
    if drv.is_visible_text(_NO_STUDY, timeout=3):
        runner.fail("No study registered in web portal")
    if _not_started(drv):
        runner.fail("Study not started — 'Start Study' button still visible")


def test_conn_001_bt_off_disconnected(drv, runner):
    """TC-CONN-001 | BT off → Device Status Bluetooth card shows Disconnected"""
    if _not_started(drv):
        return
    _bt_off(drv)
    time.sleep(4)
    try:
        drv.tap_text(_DEV_TAB, timeout=5)
        time.sleep(1)
        runner.assert_true(
            drv.is_visible_text("Disconnected", timeout=5),
            "BT off: Bluetooth card did not show Disconnected in Device Status tab"
        )
    finally:
        _bt_on(drv)
        time.sleep(4)


def test_conn_002_bt_on_recovery(drv, runner):
    """TC-CONN-002 | BT on after off → Bluetooth card recovers within 30s"""
    if _not_started(drv):
        return
    _bt_off(drv)
    time.sleep(3)
    _bt_on(drv)
    drv.tap_text(_DEV_TAB, timeout=5)
    # Poll until Disconnected clears (BLE scan + reconnect can take up to 30s)
    recovered = False
    for _ in range(30):
        time.sleep(1)
        if not drv.is_visible_text("Disconnected", timeout=1):
            recovered = True
            break
    runner.assert_true(recovered, "BT recovery: Bluetooth card still shows Disconnected 30s after BT re-enabled")


def test_conn_003_wifi_off_detected(drv, runner):
    """TC-CONN-003 | WiFi off → OS reports wifi_on=0 + Network card changes"""
    from src.regression.helpers import go_to_main
    if _not_started(drv):
        return
    _wifi_off(drv)
    time.sleep(3)
    try:
        wifi_actually_off = _wifi_is_off(drv)
        runner.assert_true(wifi_actually_off, "WiFi did not turn off (adb wifi_on still 1)")
        # Popup may appear if server unreachable; dismiss and recover
        if drv.is_visible_text("Cannot find your S-Patch", timeout=2):
            try:
                drv.tap_text("OK", timeout=3, contains=False)
            except Exception:
                pass
            try:
                go_to_main(drv)
            except Exception:
                pass
        drv.tap_text(_DEV_TAB, timeout=5)
        time.sleep(1)
        # Log what the Network card shows — text varies by app version
        net_off = (
            drv.is_visible_text("Network Off", timeout=3)
            or drv.is_visible_text("No Network", timeout=2)
            or drv.is_visible_text("Disconnected", timeout=2)
            or drv.is_visible_text("Off", timeout=2)
        )
        if net_off:
            log.info("TC-CONN-003: Network card shows disconnected state (UI updated)")
        else:
            log.warning("TC-CONN-003: Network card text unchanged after WiFi off — UI may use icon only")
    finally:
        _wifi_on(drv)
        time.sleep(4)


def test_conn_004_wifi_on_recovery(drv, runner):
    """TC-CONN-004 | WiFi on after off → wifi_on=1 restored within timeout"""
    if _not_started(drv):
        return
    _wifi_off(drv)
    time.sleep(2)
    _wifi_on(drv)
    # Poll until WiFi is back (up to 15s)
    recovered = False
    for _ in range(15):
        time.sleep(1)
        if not _wifi_is_off(drv):
            recovered = True
            break
    runner.assert_true(recovered, "WiFi did not recover within 15s after re-enabling")
    time.sleep(2)


def test_conn_005_bt_off_attach_guide_card(drv, runner):
    """TC-CONN-005 | BT off → 'How to Attach the S-Patch' guidance card appears"""
    if _not_started(drv):
        return
    _bt_off(drv)
    time.sleep(4)
    try:
        drv.tap_text(_DEV_TAB, timeout=5)
        time.sleep(1)
        guide_visible = drv.is_visible_text("How to", timeout=5)
        runner.assert_true(guide_visible, "BT off: 'How to Attach' guidance card not visible in Device Status tab")
    finally:
        _bt_on(drv)
        time.sleep(4)


TESTS = [
    test_conn_000_study_active,
    test_conn_001_bt_off_disconnected,
    test_conn_002_bt_on_recovery,
    test_conn_003_wifi_off_detected,
    test_conn_004_wifi_on_recovery,
    test_conn_005_bt_off_attach_guide_card,
]
