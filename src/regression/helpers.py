"""
Common helper functions
"""
import time
import logging
from selenium.webdriver.common.by import By

log = logging.getLogger(__name__)

# Coordinates for 1080x2400 (Pixel 7) — update if device changes
# AK app uses a gear icon (top-right) instead of hamburger menu (top-left)
MENU_BTN_X = 985  # center of gear icon bounds [954,199][1017,262]
MENU_BTN_Y = 230
STUDY_POPUP_X_BTN = (252, 358)   # X dismiss button on No Study Information popup
DIARY_X_BTN = (1009, 1226)       # X close button on Log Symptoms sheet (Pixel 7, bounds [977,1194][1040,1257])


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


def go_to_main(drv, wait_ble: int = 60):
    """App initial screen → Connect → (auto-handle Step 2/3/Start Study) → main measurement screen.

    Study registered + started: only the Connect button is shown on app restart (no serial input).
    Study not registered: enter serial + Connect.
    BLE error popups (950/963) are handled automatically.
    """
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

    drv.tap_text("Connect", timeout=10, contains=False)
    log.info("[go_to_main] Connect tapped, waiting up to %ds for BLE connection", wait_ble)

    deadline = time.monotonic() + wait_ble
    while time.monotonic() < deadline:
        # Main measurement screen (AK: "Log Symptoms" button visible = study in progress)
        if drv.is_visible_text("Log Symptoms", timeout=1):
            log.info("[go_to_main] Main measurement screen reached")
            return

        # Start Study screen (AK specific — after Step 3)
        if drv.is_visible_text("Start Study", timeout=1):
            log.info("[go_to_main] Start Study screen detected → tapping Start Study")
            drv.tap_text("Start Study", timeout=5, contains=False)
            time.sleep(2)
            continue

        # Step 3 — Review Study Setting (study registered, Step 2 skipped)
        if drv.is_visible_text("Review Study Setting", timeout=1):
            log.info("[go_to_main] Step 3 detected → Continue")
            drv.tap_text("Continue", timeout=5, contains=False)
            time.sleep(1)
            continue

        # Step 2 — Check Incoming Signal (study not registered)
        if drv.is_visible_text("Check Incoming Signal", timeout=1):
            log.info("[go_to_main] Step 2 detected → Continue")
            drv.tap_text("Continue", timeout=5, contains=False)
            time.sleep(1)
            continue

        # AK error popup — Cannot find your S-Patch (950)
        if drv.is_visible_text("Cannot find your S-Patch", timeout=1):
            log.warning("[go_to_main] BLE error popup (950) detected → Ok")
            try:
                drv.tap_text("OK", timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(2)
            continue

        # AK error popup — Reset your S-Patch (963)
        if drv.is_visible_text("Reset your S-Patch", timeout=1):
            log.warning("[go_to_main] BLE error popup (963) detected → Ok")
            try:
                drv.tap_text("OK", timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(2)
            continue

        time.sleep(1)

    raise Exception(f"Main screen not reached after {wait_ble}s — 'Log Symptoms' not visible")


def open_menu(drv, wait: float = 2.0):
    for attempt in range(3):
        drv.drv.tap([(MENU_BTN_X, MENU_BTN_Y)])
        time.sleep(wait)
        if drv.is_visible_text("Setting", timeout=2):
            return
        log.warning("[open_menu] Menu did not open, retrying %d/3", attempt + 1)
        time.sleep(0.5)
    raise Exception("open_menu: Failed to open menu after 3 attempts")


def close_menu(drv):
    drv.drv.press_keycode(4)
    time.sleep(0.5)
