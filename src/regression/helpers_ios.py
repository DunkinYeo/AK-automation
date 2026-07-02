"""
iOS navigation helpers — mirrors helpers.py interface for IOSDriver.

NEW FILE — does not modify src/regression/helpers.py (Android) in any way.
Key differences from Android:
  - No press_keycode(4) — uses swipe-down or Done/Cancel buttons
  - No ADB-based checks
  - No ANDROID_UIAUTOMATOR locators
"""
import time
import logging
from appium.webdriver.common.appiumby import AppiumBy

log = logging.getLogger(__name__)

# ── Screen signatures (same text as Android — UI is identical) ──────────────
_SCREEN_SIGNATURES = [
    ("start_study",    ["Start Study"],                                        "Start Study Screen"),
    ("log_symptoms",   ["Log Symptoms", "My Study Progress", "Device Status"], "Main Screen (Study Running)"),
    ("review_setting", ["Review Study Setting"],                               "Step 3 (Review Study Setting)"),
    ("check_signal",   ["Check Incoming Signal"],                              "Step 2 (Check Incoming Signal)"),
    ("connect_patch",  ["Connect Your S-Patch"],                               "Step 1 (Patch Serial Number)"),
    ("cannot_find",    ["Cannot find your S-Patch"],                           "Error: Cannot Find S-Patch (950)"),
    ("reset_patch",    ["Reset your S-Patch"],                                 "Error: Reset S-Patch (963)"),
    ("no_study",       ["No Study Information", "No study information"],       "Error: No Study Information"),
    ("bt_disabled",    ["Bluetooth not enabled"],                              "Error: Bluetooth Disabled"),
    ("upload",         ["Upload"],                                             "Upload Screen"),
]


def detect_current_screen(drv, timeout: int = 1) -> tuple:
    for screen_id, texts, label in _SCREEN_SIGNATURES:
        for text in texts:
            if drv.is_visible_text(text, timeout=timeout):
                return screen_id, label
    return "unknown", "Unknown Screen"


def _capture_diagnostics(drv, tag: str):
    try:
        drv.screenshot(tag)
    except Exception as e:
        log.debug("[diag-ios] screenshot failed: %s", e)
    try:
        bundle = drv.drv.current_package
        log.info("[diag-ios] %s — bundle=%s", tag, bundle)
    except Exception as e:
        log.debug("[diag-ios] bundle query failed: %s", e)


def close_sheet(drv):
    """
    Close a bottom sheet on iOS.
    Tries Done/Cancel buttons first; falls back to swipe-down gesture.
    """
    for btn in ["Done", "Cancel", "Close"]:
        if drv.is_visible_text(btn, timeout=1):
            try:
                drv.tap_text(btn, timeout=2, contains=False)
                time.sleep(0.5)
                return
            except Exception:
                pass
    # Swipe down to dismiss bottom sheet
    try:
        size = drv.drv.get_window_size()
        w, h = size["width"], size["height"]
        drv.drv.swipe(w // 2, int(h * 0.4), w // 2, int(h * 0.8), 300)
        time.sleep(0.5)
    except Exception:
        pass


def reset_to_step1(drv, hard: bool = True):
    bundle_id = drv.cfg.get("bundle_id", "")
    if hard:
        log.info("[setup-ios] App restart → Step 1")
        try:
            drv.drv.terminate_app(bundle_id)
        except Exception:
            pass
        time.sleep(1)
        try:
            drv.drv.activate_app(bundle_id)
        except Exception:
            pass
        time.sleep(2)
    else:
        log.info("[setup-ios] Back swipe → Step 1")
        for _ in range(5):
            if drv.is_visible_text("Connect Your S-Patch", timeout=2):
                break
            try:
                size = drv.drv.get_window_size()
                drv.drv.swipe(0, size["height"] // 2,
                              size["width"] // 2, size["height"] // 2, 300)
            except Exception:
                pass
            time.sleep(0.8)


def _find_serial_input(drv):
    """Find serial number text field on iOS."""
    for locator in [
        (AppiumBy.ACCESSIBILITY_ID, "Enter the Serial Number here."),
        (AppiumBy.IOS_PREDICATE_STRING, 'type == "XCUIElementTypeTextField"'),
        (AppiumBy.IOS_PREDICATE_STRING, 'type == "XCUIElementTypeSecureTextField"'),
    ]:
        try:
            els = drv.drv.find_elements(*locator)
            if els:
                return els[0]
        except Exception:
            pass
    return None


def go_to_step2(drv, wait_ble: int = 45):
    if not drv.is_visible_text("Connect Your S-Patch", timeout=5):
        raise Exception("Not on Step 1 screen — please call reset_to_step1() first")

    serial = drv.cfg.get("test_serial_number", "680150")
    el = _find_serial_input(drv)
    if el:
        el.clear()
        el.send_keys(serial)
        time.sleep(0.5)
    drv.tap_text("Connect", timeout=5, contains=False)

    deadline = time.monotonic() + wait_ble
    while time.monotonic() < deadline:
        if drv.is_visible_text("Check Incoming Signal", timeout=2):
            return
        if drv.is_visible_text("Review Study Setting", timeout=1):
            raise Exception("Step 2 skipped — study is registered on web")
        time.sleep(1)
    raise Exception(f"Failed to enter Step 2 after {wait_ble}s")


def _is_menu_open(drv, timeout: int = 2) -> bool:
    indicators = ["Setting", "Settings", "Version Information", "Guide", "Patch Placement"]
    for text in indicators:
        if drv.is_visible_text(text, timeout=timeout):
            return True
    return False


def open_menu(drv, wait: float = 2.0):
    """
    Open the hamburger/settings menu on iOS.
    Strategy 1: ACCESSIBILITY_ID (most reliable)
    Strategy 2: Any button in top 25% of screen
    Strategy 3: Coordinate tap at common top-right / top-left positions
    """
    try:
        drv.screenshot("open_menu_before_ios")
    except Exception:
        pass

    def _try_tap() -> bool:
        # Strategy 1: accessibility ID
        for desc in ["Open navigation drawer", "Menu", "Open menu", "Navigation",
                     "Settings", "Setting"]:
            try:
                el = drv.drv.find_element(AppiumBy.ACCESSIBILITY_ID, desc)
                el.click()
                log.info("[open_menu-iOS] ACCESSIBILITY_ID '%s' clicked", desc)
                return True
            except Exception:
                pass

        # Strategy 2: any Button in top 25% of screen
        try:
            h = drv.drv.get_window_size()["height"]
            top_threshold = int(h * 0.25)
            for element_type in ["XCUIElementTypeButton", "XCUIElementTypeImage"]:
                els = drv.drv.find_elements(
                    AppiumBy.IOS_PREDICATE_STRING,
                    f'type == "{element_type}"'
                )
                for el in els:
                    try:
                        loc = el.location
                        if loc["y"] < top_threshold:
                            el.click()
                            log.info("[open_menu-iOS] %s at (%d,%d) clicked",
                                     element_type, loc["x"], loc["y"])
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        # Strategy 3: coordinate fallback
        try:
            size = drv.drv.get_window_size()
            w, h = size["width"], size["height"]
            for pct_x, pct_y, label in [
                (0.915, 0.07, "top-right"),
                (0.085, 0.07, "top-left"),
                (0.915, 0.05, "top-right-high"),
                (0.085, 0.05, "top-left-high"),
            ]:
                x, y = int(w * pct_x), int(h * pct_y)
                drv.drv.tap([(x, y)])
                log.info("[open_menu-iOS] Coordinate tap %s (%d,%d)", label, x, y)
                return True
        except Exception:
            pass

        return False

    for attempt in range(3):
        _try_tap()
        time.sleep(wait)
        if _is_menu_open(drv, timeout=2):
            log.info("[open_menu-iOS] Menu opened on attempt %d", attempt + 1)
            return
        log.warning("[open_menu-iOS] Menu did not open (attempt %d/3)", attempt + 1)
        try:
            drv.screenshot(f"open_menu_fail_ios_{attempt + 1}")
        except Exception:
            pass
        time.sleep(0.5)

    try:
        drv.screenshot("open_menu_failed_final_ios")
    except Exception:
        pass
    device_info = ""
    try:
        info = drv.get_device_info()
        device_info = (f"\n  Device: {info.get('model', '?')} iOS {info.get('ios_version', '?')}")
    except Exception:
        pass
    raise Exception(
        "open_menu: failed to open menu after 3 attempts (iOS). "
        "Check screenshot open_menu_failed_final_ios."
        f"{device_info}"
    )


def close_menu(drv):
    """Close menu on iOS via swipe-left or back button."""
    try:
        size = drv.drv.get_window_size()
        drv.drv.swipe(size["width"] // 2, size["height"] // 2,
                      0, size["height"] // 2, 300)
        time.sleep(0.5)
    except Exception:
        pass


def go_to_main(drv, wait_ble: int = 120):
    """
    Navigate to main measurement screen on iOS.
    Same state-machine logic as Android version — text-based detection works
    identically since the app UI text is the same across platforms.
    """
    try:
        bundle_id = drv.cfg.get("bundle_id", "")
        if bundle_id:
            drv.drv.activate_app(bundle_id)
            time.sleep(1.5)
    except Exception:
        pass

    # Already on main screen (but not on pre-study Start Study screen)
    if not drv.is_visible_text("Start Study", timeout=1, contains=False):
        for _indicator in ["Log Symptoms", "My Study Progress", "Device Status"]:
            if drv.is_visible_text(_indicator, timeout=3):
                log.info("[go_to_main-iOS] Already on main screen (%s visible)", _indicator)
                return

    # Dismiss lingering popups
    for popup_text, btn in [("Cannot find your S-Patch", ["Ok", "OK"]),
                             ("Reset your S-Patch",       ["Ok", "OK"]),
                             ("Bluetooth not enabled",    ["Ok", "OK"]),
                             ("No Study Information",     ["Confirm", "Ok", "OK"]),
                             ("No study information",     ["Confirm", "Ok", "OK"])]:
        if drv.is_visible_text(popup_text, timeout=1):
            log.info("[go_to_main-iOS] Dismissing popup: %s", popup_text)
            try:
                drv.tap_text(btn, timeout=3, contains=False)
                time.sleep(0.5)
            except Exception:
                pass

    serial = drv.cfg.get("test_serial_number", "")

    # Serial entry
    el = _find_serial_input(drv)
    if el:
        try:
            el.clear()
            el.send_keys(serial)
            time.sleep(0.5)
            log.info("[go_to_main-iOS] Serial entered: %s", serial)
        except Exception:
            pass
    else:
        log.info("[go_to_main-iOS] No input field — connecting directly")

    if drv.is_visible_text("Connect", timeout=5, contains=False):
        try:
            drv.tap_text("Connect", timeout=5, contains=False)
        except Exception:
            pass

    log.info("[go_to_main-iOS] Waiting up to %ds for main screen", wait_ble)

    _start_ts = time.monotonic()
    _last_screen_id = None
    _connect_attempts = 0
    _ble_error_count  = 0
    _DIAG_AFTER_N     = 2
    _SLOW_AFTER_N     = 4

    deadline = time.monotonic() + wait_ble

    while time.monotonic() < deadline:
        elapsed = int(time.monotonic() - _start_ts)
        screen_id, screen_label = detect_current_screen(drv, timeout=1)

        if screen_id != _last_screen_id:
            log.info("[go_to_main-iOS] Screen: %s (%ds)", screen_label, elapsed)
            _last_screen_id = screen_id

        if screen_id == "log_symptoms":
            log.info("[go_to_main-iOS] Main screen reached (%ds)", elapsed)
            return

        elif screen_id == "start_study":
            try:
                drv.tap_text("Start Study", timeout=5, contains=False)
                time.sleep(2)
            except Exception:
                pass

        elif screen_id == "review_setting":
            time.sleep(1)
            try:
                drv.tap_text("Continue", timeout=5, contains=True)
                time.sleep(1)
            except Exception as e:
                log.warning("[go_to_main-iOS] Step 3 Continue failed: %s", e)

        elif screen_id == "check_signal":
            time.sleep(2)
            try:
                drv.tap_text("Continue", timeout=5, contains=True)
                time.sleep(1)
            except Exception as e:
                log.warning("[go_to_main-iOS] Step 2 Continue failed: %s", e)

        elif screen_id == "connect_patch":
            _connect_attempts += 1
            log.info("[go_to_main-iOS] Step 1 attempt #%d (%ds)", _connect_attempts, elapsed)
            if _connect_attempts == _DIAG_AFTER_N:
                _capture_diagnostics(drv, f"go_to_main_ios_ble_retry_{_connect_attempts}")
            if _connect_attempts > _SLOW_AFTER_N:
                log.warning("[go_to_main-iOS] Repeated BLE failure (%d attempts)", _connect_attempts)
                _capture_diagnostics(drv, f"go_to_main_ios_ble_stuck_{_connect_attempts}")
                time.sleep(5)
            el = _find_serial_input(drv)
            if el:
                try:
                    el.clear()
                    el.send_keys(serial)
                    time.sleep(0.5)
                except Exception:
                    pass
            try:
                drv.tap_text("Connect", timeout=5, contains=False)
                time.sleep(2)
            except Exception:
                pass

        elif screen_id in ("cannot_find", "reset_patch"):
            _ble_error_count += 1
            log.warning("[go_to_main-iOS] BLE error (%s) count: %d", screen_id, _ble_error_count)
            try:
                drv.tap_text(["OK", "Ok"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(2)

        elif screen_id in ("no_study", "bt_disabled"):
            try:
                drv.tap_text(["Confirm", "Ok", "OK"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(1)

        else:
            # Dismiss any iOS system popup that might be blocking
            drv.dismiss_unexpected_popups()
            time.sleep(1)

    # Timeout
    elapsed_total = int(time.monotonic() - _start_ts)
    final_screen_id, final_screen_label = detect_current_screen(drv, timeout=2)
    log.error("[go_to_main-iOS] TIMEOUT after %ds — screen: %s", elapsed_total, final_screen_label)
    _capture_diagnostics(drv, "go_to_main_ios_timeout")

    try:
        bundle = drv.drv.current_package
    except Exception:
        bundle = "unknown"

    raise Exception(
        f"Main screen not reached after {wait_ble}s (iOS)\n"
        f"  Current screen:   {final_screen_label}\n"
        f"  Connect attempts: {_connect_attempts}\n"
        f"  BLE errors:       {_ble_error_count}\n"
        f"  Bundle:           {bundle}\n"
        f"  Expected:         Log Symptoms (Main Screen)"
    )
