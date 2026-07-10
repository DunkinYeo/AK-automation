"""
TC-CONN: Connectivity (BT / WiFi) regression tests during active study (AK)
Requires study active + physical S-Patch patch within BLE range.

AK Device Status tab — BT disconnect indicators (confirmed via UI dump):
  - Bluetooth card: "Disconnected" (appears within ~5s of BT off)
  - "How to Attacth the S-Patch" guidance card (app typo: "Attacth")
    → stored as single element with embedded newlines: "How to\nAttacth\nthe S-Patch"
    → search using "How to" (prefix substring) to avoid typo/newline issues

AK Device Status tab — WiFi off indicators:
  - Network card may show "Disconnected" (text) or icon-only change
  - ADB: settings get global wifi_on == 0

Test flow: navigate to Device Status tab FIRST, then toggle, then poll for change.
"""
import subprocess
import time
import logging

log = logging.getLogger(__name__)

_NO_STUDY    = "No study information"
_START_STUDY = "Start Study"
_DEV_TAB     = "Device Status"
_BT_DISCONNECTED = "Disconnected"   # Bluetooth card value when BT off
_HOW_TO_ATTACH   = "How to"         # guidance card prefix ("How to\nAttacth\nthe S-Patch")
_CONNECT_BTN     = "Connect"        # reconnect CTA (appears after extended disconnection)

_BT_POLL_TIMEOUT     = 20   # seconds to wait for BT state change
_BT_RECOVERY_TIMEOUT = 30   # seconds to wait for BT reconnection
_WIFI_POLL_TIMEOUT   = 15   # seconds to wait for WiFi recovery


def _not_started(drv) -> bool:
    return drv.is_visible_text(_START_STUDY, timeout=2)


def _adb(drv, *args):
    udid = drv.cfg.get("udid", "")
    cmd = ["adb"]
    if udid:
        cmd += ["-s", udid]
    cmd += list(args)
    subprocess.run(cmd, capture_output=True, timeout=10)


def _adb_out(drv, *args) -> str:
    udid = drv.cfg.get("udid", "")
    cmd = ["adb"] + (["-s", udid] if udid else []) + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""


def _bt_is_off(drv) -> bool:
    """Verify BT is actually off via dumpsys."""
    out = _adb_out(drv, "shell", "dumpsys", "bluetooth_manager")
    for line in out.splitlines():
        if "enabled:" in line:
            return "false" in line.lower()
    return False


def _bt_off(drv) -> bool:
    """Try to disable BT. Returns True if BT actually went off."""
    for args in (
        ("shell", "svc", "bluetooth", "disable"),
        ("shell", "cmd", "bluetooth_manager", "disable"),
    ):
        try:
            _adb(drv, *args)
        except Exception:
            pass
    # Poll up to 20s — BT stack teardown lags the command on many devices
    # (same window bt_disconnect.py uses; a fixed 2s single check
    # false-flagged Pixel 7 as "not supported" while the long-run
    # cycle on the same device worked fine — 2026-07-10)
    for _ in range(10):
        time.sleep(2)
        if _bt_is_off(drv):
            return True
    log.warning("_bt_off: BT still ON after disable commands (device/OS may not support ADB BT toggle)")
    return False


def _bt_on(drv):
    for args in (
        ("shell", "svc", "bluetooth", "enable"),
        ("shell", "cmd", "bluetooth_manager", "enable"),
    ):
        try:
            _adb(drv, *args)
        except Exception:
            pass


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


def _go_device_status(drv):
    drv.tap_text(_DEV_TAB, timeout=5)
    time.sleep(0.5)


def _poll_until(drv, text: str, appear: bool, timeout: int) -> tuple[bool, float]:
    """Poll until text appears (appear=True) or disappears (appear=False).
    Returns (success, elapsed_seconds).
    """
    t0 = time.monotonic()
    for _ in range(timeout * 2):
        time.sleep(0.5)
        visible = drv.is_visible_text(text, timeout=1)
        if appear and visible:
            return True, round(time.monotonic() - t0, 1)
        if not appear and not visible:
            return True, round(time.monotonic() - t0, 1)
    return False, round(time.monotonic() - t0, 1)


def _bt_on_safe(drv):
    try:
        _bt_on(drv)
    except Exception:
        pass


_BT_SKIP_REASON = "ADB BT toggle not supported on this device/OS — skipped"


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
    """TC-CONN-001 | BT off → Device Status Bluetooth card shows 'Disconnected' (within 20s)"""
    if _not_started(drv):
        return
    _go_device_status(drv)
    if not _bt_off(drv):
        runner.skip(_BT_SKIP_REASON)
    ok, elapsed = _poll_until(drv, _BT_DISCONNECTED, appear=True, timeout=_BT_POLL_TIMEOUT)
    _bt_on_safe(drv)
    if ok:
        log.info("TC-CONN-001: Bluetooth 'Disconnected' appeared in %.1fs after BT off", elapsed)
    runner.assert_true(ok, f"BT off: Bluetooth card did not show 'Disconnected' within {_BT_POLL_TIMEOUT}s")


def test_conn_002_bt_off_timing(drv, runner):
    """TC-CONN-002 | BT off → measure elapsed time until 'Disconnected' appears (≤ 20s)"""
    if _not_started(drv):
        return
    _go_device_status(drv)
    if not _bt_off(drv):
        runner.skip(_BT_SKIP_REASON)
    ok, elapsed = _poll_until(drv, _BT_DISCONNECTED, appear=True, timeout=_BT_POLL_TIMEOUT)
    _bt_on_safe(drv)
    if ok:
        log.info("TC-CONN-002: BT disconnect reflected in UI in %.1fs", elapsed)
    runner.assert_true(ok, f"BT off: 'Disconnected' not detected within {_BT_POLL_TIMEOUT}s")
    runner.assert_true(elapsed <= _BT_POLL_TIMEOUT, f"BT disconnect too slow: {elapsed}s (≤ {_BT_POLL_TIMEOUT}s expected)")


def test_conn_003_bt_off_attach_card(drv, runner):
    """TC-CONN-003 | BT off → 'How to Attach' guidance card appears (within 20s)"""
    if _not_started(drv):
        return
    _go_device_status(drv)
    if not _bt_off(drv):
        runner.skip(_BT_SKIP_REASON)
    # Card text in app: "How to\nAttacth\nthe S-Patch" (embedded newlines + app typo)
    # Use prefix "How to" for reliable detection
    ok, elapsed = _poll_until(drv, _HOW_TO_ATTACH, appear=True, timeout=_BT_POLL_TIMEOUT)
    _bt_on_safe(drv)
    if ok:
        log.info("TC-CONN-003: 'How to Attach' guidance card appeared in %.1fs after BT off", elapsed)
    runner.assert_true(ok, f"BT off: 'How to Attach' guidance card not visible within {_BT_POLL_TIMEOUT}s")


def test_conn_004_bt_on_recovery(drv, runner):
    """TC-CONN-004 | BT on after off → Bluetooth card recovers ('Disconnected' clears) within 30s"""
    if _not_started(drv):
        return
    _go_device_status(drv)
    if not _bt_off(drv):
        runner.skip(_BT_SKIP_REASON)
    _poll_until(drv, _BT_DISCONNECTED, appear=True, timeout=_BT_POLL_TIMEOUT)
    _bt_on(drv)
    ok, elapsed = _poll_until(drv, _BT_DISCONNECTED, appear=False, timeout=_BT_RECOVERY_TIMEOUT)
    if ok:
        log.info("TC-CONN-004: BT reconnected ('Disconnected' cleared) in %.1fs", elapsed)
    runner.assert_true(ok, f"BT recovery: Bluetooth card still shows 'Disconnected' {_BT_RECOVERY_TIMEOUT}s after BT re-enabled")


def _is_wifi_adb(drv) -> bool:
    """Return True if ADB is connected via WiFi (IP:port) — WiFi-off tests must be skipped."""
    udid = drv.cfg.get("udid", "")
    return ":" in udid


def test_conn_005_wifi_off_network_card(drv, runner):
    """TC-CONN-005 | WiFi off → OS confirms wifi_on=0 (Network card may show icon change only)"""
    if _not_started(drv):
        return
    if _is_wifi_adb(drv):
        log.info("TC-CONN-005: skipped — ADB connected via WiFi; disabling WiFi would drop the session")
        return
    _go_device_status(drv)
    _wifi_off(drv)
    try:
        wifi_actually_off = _wifi_is_off(drv)
        runner.assert_true(wifi_actually_off, "WiFi did not turn off (adb wifi_on still 1)")

        net_off_candidates = ["Network Off", "No Network", "Disconnected", "Off"]
        net_off = any(drv.is_visible_text(t, timeout=3) for t in net_off_candidates)
        if net_off:
            log.info("TC-CONN-005: Network card shows disconnected text after WiFi off")
        else:
            log.info("TC-CONN-005: Network card uses icon-only indicator (no text change) — OS-level confirmed")
    finally:
        _wifi_on(drv)
        time.sleep(4)


def test_conn_006_wifi_on_recovery(drv, runner):
    """TC-CONN-006 | WiFi on after off → wifi_on=1 restored within 15s"""
    if _not_started(drv):
        return
    if _is_wifi_adb(drv):
        log.info("TC-CONN-006: skipped — ADB connected via WiFi; disabling WiFi would drop the session")
        return
    _wifi_off(drv)
    time.sleep(2)
    _wifi_on(drv)
    recovered = False
    for _ in range(_WIFI_POLL_TIMEOUT * 2):
        time.sleep(0.5)
        if not _wifi_is_off(drv):
            recovered = True
            break
    runner.assert_true(recovered, f"WiFi did not recover within {_WIFI_POLL_TIMEOUT}s after re-enabling")


def test_conn_007_connect_btn_tap_recovery(drv, runner):
    """TC-CONN-007 | BT off + app background→foreground → popup appears → Connect screen → BT on → tap Connect → main screen recovers

    When app is resumed from background with BLE disconnected:
    1. "Bluetooth not enabled (102)" popup appears → screenshot + dismiss with Ok
    2. Connect screen shown (bold gradient button, all cards '-') → assertion
    3. Enable BT first, then tap Connect → 'Log Symptoms' returns
    """
    if _not_started(drv):
        return
    pkg = drv.cfg.get("app_package")

    if not _bt_off(drv):
        runner.skip(_BT_SKIP_REASON)
    time.sleep(1)

    # Send app to background then foreground — triggers 102 popup
    drv.drv.press_keycode(3)   # HOME key
    time.sleep(2)
    drv.drv.activate_app(pkg)
    time.sleep(1)

    # 102 popup: "Bluetooth not enabled (102)" with "Ok" button
    if drv.is_visible_text("Bluetooth not enabled", timeout=5):
        log.info("TC-CONN-007: 102 popup appeared — capturing screenshot then dismissing")
        try:
            drv.screenshot("conn_007_102_popup")
        except Exception:
            pass
        try:
            drv.tap_text(["Ok", "OK"], timeout=5, contains=False)
        except Exception:
            pass
        time.sleep(1)

    # Also handle 950 popup if it appears instead
    if drv.is_visible_text("Cannot find your S-Patch", timeout=3):
        log.info("TC-CONN-007: 950 popup appeared — capturing screenshot then dismissing")
        try:
            drv.screenshot("conn_007_950_popup")
        except Exception:
            pass
        try:
            drv.tap_text(["Ok", "OK"], timeout=5, contains=False)
        except Exception:
            pass
        time.sleep(1)

    # Assert: Connect screen must be visible
    connect_visible = drv.is_visible_text(_CONNECT_BTN, timeout=5)
    runner.assert_true(connect_visible, "BT off + app resume: 'Connect' screen not shown after popup dismiss")
    if not connect_visible:
        _bt_on_safe(drv)
        return

    log.info("TC-CONN-007: Connect screen confirmed — enabling BT then tapping Connect")

    # Enable BT FIRST (wait for adapter), then tap Connect
    _bt_on(drv)
    time.sleep(3)
    drv.tap_text(_CONNECT_BTN, timeout=5, contains=False)

    # Poll for main screen recovery ('Log Symptoms' returns)
    ok, elapsed = _poll_until(drv, "Log Symptoms", appear=True, timeout=45)
    if ok:
        log.info("TC-CONN-007: Main screen recovered ('Log Symptoms' visible) in %.1fs", elapsed)
    runner.assert_true(ok, "BT reconnect via Connect button: 'Log Symptoms' did not return within 45s")


TESTS = [
    test_conn_000_study_active,
    test_conn_001_bt_off_disconnected,
    test_conn_002_bt_off_timing,
    test_conn_003_bt_off_attach_card,
    test_conn_004_bt_on_recovery,
    test_conn_005_wifi_off_network_card,
    test_conn_006_wifi_on_recovery,
    test_conn_007_connect_btn_tap_recovery,
]
