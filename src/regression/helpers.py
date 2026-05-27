"""
Common helper functions
"""
import time
import logging
from selenium.webdriver.common.by import By
from appium.webdriver.common.appiumby import AppiumBy

log = logging.getLogger(__name__)

STUDY_POPUP_X_BTN = None   # kept for legacy import compatibility — no longer used
DIARY_X_BTN = None         # kept for legacy import compatibility — use close_sheet() instead


def close_sheet(drv):
    """Close a bottom sheet (Log Symptoms, etc.) using Back key — device-independent."""
    drv.drv.press_keycode(4)
    time.sleep(0.8)


def reset_to_step1(drv, hard: bool = True):
    """
    Navigate to the Step 1 (Connect Your S-Patch) screen.
    hard=True  : Force-quit and restart the app (note: BLE will disconnect)
    hard=False : Press back repeatedly to return to Step 1 (BLE retained)
    """
    pkg = drv.cfg.get("app_package")

    if hard:
        log.info("[setup] App restart → Step 1")
        try:
            drv.drv.terminate_app(pkg)
        except Exception:
            pass
        time.sleep(1)
        try:
            drv.drv.activate_app(pkg)
        except Exception:
            act = drv.cfg.get("app_activity")
            if act:
                drv.drv.start_activity(pkg, act)
        time.sleep(2)
    else:
        log.info("[setup] Back key → Step 1 (BLE retained)")
        for _ in range(5):
            if drv.is_visible_text("Connect Your S-Patch", timeout=2):
                break
            drv.drv.press_keycode(4)
            time.sleep(0.8)
        time.sleep(0.5)


def go_to_step2(drv, wait_ble: int = 45):
    """Enter serial on Step 1, then proceed to Step 2. wait_ble: BLE connection wait time (seconds)

    Note: If a study is registered on the web, Step 2 may be passed quickly,
    auto-entering Step 3 (Review Study Setting) or the main screen.
    TC-SIG/STUDY tests are recommended to run without a registered study.
    """
    if not drv.is_visible_text("Connect Your S-Patch", timeout=5):
        raise Exception("Not on Step 1 screen — please call reset_to_step1() first")

    serial = drv.cfg.get("test_serial_number", "680150")
    el = drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")
    el.clear()
    el.send_keys(serial)
    time.sleep(0.5)
    drv.tap_text("Connect", timeout=5, contains=False)

    # Wait for BLE connection + Step 2 loading
    deadline = time.monotonic() + wait_ble
    while time.monotonic() < deadline:
        if drv.is_visible_text("Check Incoming Signal", timeout=2):
            return
        # If study is registered on web, Step 2 is passed quickly → warn and fail
        if drv.is_visible_text("Review Study Setting", timeout=1):
            raise Exception("Step 2 skipped — study is registered on web. Retry after unregistering study")
        if drv.is_visible_text("Study Information", timeout=1):
            raise Exception("Step 2 skipped — study already in progress. Retry after ending study")
        time.sleep(1)

    raise Exception(f"Failed to enter Step 2 ('Check Incoming Signal' not displayed after {wait_ble}s)")


def go_to_main(drv, wait_ble: int = 120):
    """App initial screen → Connect → (auto-handle Step 2/3/Start Study) → main measurement screen.

    Study registered + started: only the Connect button is shown on app restart (no serial input).
    Study not registered: enter serial + Connect.
    BLE error popups (950/963) are handled automatically.
    """
    # Bring the AK app to foreground first (may be behind another app or in background)
    try:
        pkg = drv.cfg.get("app_package")
        if pkg:
            drv.drv.activate_app(pkg)
            time.sleep(1.5)
    except Exception:
        pass

    # Already on main screen — only "Log Symptoms" is a reliable indicator.
    # "My Study Progress" also appears on the disconnected Start Study screen,
    # so it cannot be used here.
    if drv.is_visible_text("Log Symptoms", timeout=3):
        log.info("[go_to_main] Already on main screen")
        return

    # Dismiss any lingering popups before navigating
    for popup_text, btn in [("Cannot find your S-Patch", ["Ok", "OK"]),
                             ("Reset your S-Patch",       ["Ok", "OK"]),
                             ("Bluetooth not enabled",    ["Ok", "OK"]),
                             ("No Study Information",     ["Confirm", "Ok", "OK"]),
                             ("No study information",     ["Confirm", "Ok", "OK"])]:
        if drv.is_visible_text(popup_text, timeout=1):
            log.info("[go_to_main] Dismissing lingering popup: %s", popup_text)
            try:
                drv.tap_text(btn, timeout=3, contains=False)
                time.sleep(0.5)
            except Exception:
                pass

    # Enter serial if input field is present (not registered state)
    try:
        el = drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")
        serial = drv.cfg.get("test_serial_number", "")
        el.clear()
        el.send_keys(serial)
        time.sleep(0.5)
        log.info("[go_to_main] Serial entered: %s", serial)
    except Exception:
        log.info("[go_to_main] No EditText — connecting directly with registered device")

    # Connect button may not exist if app auto-navigated past it
    if drv.is_visible_text("Connect", timeout=5, contains=False):
        try:
            drv.tap_text("Connect", timeout=5, contains=False)
        except Exception:
            pass
    else:
        log.info("[go_to_main] No Connect button visible — proceeding to wait loop")
    log.info("[go_to_main] Waiting up to %ds for main screen", wait_ble)

    deadline = time.monotonic() + wait_ble
    while time.monotonic() < deadline:
        # Main measurement screen — only "Log Symptoms" is reliable
        if drv.is_visible_text("Log Symptoms", timeout=1):
            log.info("[go_to_main] Main measurement screen reached")
            return

        # Start Study screen (AK specific — after Step 3)
        if drv.is_visible_text("Start Study", timeout=1):
            log.info("[go_to_main] Start Study screen detected → tapping")
            try:
                drv.tap_text("Start Study", timeout=5, contains=False)
                time.sleep(2)
            except Exception:
                pass
            continue

        # Step 3 — Review Study Setting
        if drv.is_visible_text("Review Study Setting", timeout=1):
            log.info("[go_to_main] Step 3 detected → Continue")
            time.sleep(1)
            try:
                drv.tap_text("Continue", timeout=5, contains=True)
                time.sleep(1)
            except Exception as e:
                log.warning("[go_to_main] Step 3 Continue tap failed: %s", e)
            continue

        # Step 2 — Check Incoming Signal
        if drv.is_visible_text("Check Incoming Signal", timeout=1):
            log.info("[go_to_main] Step 2 detected → Continue")
            time.sleep(2)  # allow button to become interactive
            try:
                drv.tap_text("Continue", timeout=5, contains=True)
                time.sleep(1)
            except Exception as e:
                log.warning("[go_to_main] Step 2 Continue tap failed: %s", e)
            continue

        # Returned to Step 1 — re-enter serial and retry Connect
        if drv.is_visible_text("Connect Your S-Patch", timeout=1):
            log.info("[go_to_main] Returned to Step 1 — re-entering serial and retrying Connect")
            try:
                el = drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")
                serial = drv.cfg.get("test_serial_number", "")
                el.clear()
                el.send_keys(serial)
                time.sleep(0.5)
            except Exception:
                pass
            try:
                drv.tap_text("Connect", timeout=5, contains=False)
            except Exception:
                pass
            time.sleep(2)
            continue

        # AK error popup — Cannot find your S-Patch (950)
        if drv.is_visible_text("Cannot find your S-Patch", timeout=1):
            log.warning("[go_to_main] BLE error popup (950) detected → Ok")
            try:
                drv.tap_text(["OK", "Ok"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(2)
            continue

        # AK error popup — Reset your S-Patch (963)
        if drv.is_visible_text("Reset your S-Patch", timeout=1):
            log.warning("[go_to_main] BLE error popup (963) detected → Ok")
            try:
                drv.tap_text(["OK", "Ok"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(2)
            continue

        # No Study Information popup
        if (drv.is_visible_text("No Study Information", timeout=1)
                or drv.is_visible_text("No study information", timeout=1)):
            log.warning("[go_to_main] No Study Information popup → dismissing")
            try:
                drv.tap_text(["Confirm", "Ok", "OK"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(1)
            continue

        time.sleep(1)

    raise Exception(f"Main screen not reached after {wait_ble}s — 'Log Symptoms' not visible")


def open_menu(drv, wait: float = 2.0):
    for attempt in range(3):
        try:
            el = drv.drv.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR,
                'new UiSelector().className("android.widget.ImageButton").instance(0)'
            )
            el.click()
        except Exception:
            # Fallback: tap gear icon position as % of screen size (device-independent)
            try:
                size = drv.drv.get_window_size()
                x = int(size["width"]  * 0.915)
                y = int(size["height"] * 0.096)
                drv.drv.tap([(x, y)])
            except Exception:
                pass
        time.sleep(wait)
        if drv.is_visible_text("Setting", timeout=2):
            return
        log.warning("[open_menu] Menu did not open, retrying %d/3", attempt + 1)
        time.sleep(0.5)
    raise Exception("open_menu: failed to open menu after 3 attempts")


def close_menu(drv):
    drv.drv.press_keycode(4)
    time.sleep(0.5)
