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

# ── Screen signatures — ordered from deepest (main) to shallowest (step 1) ──
# Each entry: (screen_id, [indicator_texts], human_readable_label)
_SCREEN_SIGNATURES = [
    ("log_symptoms",   ["Log Symptoms"],                              "Main Screen (Study Running)"),
    ("start_study",    ["Start Study"],                               "Start Study Screen"),
    ("review_setting", ["Review Study Setting"],                      "Step 3 (Review Study Setting)"),
    ("check_signal",   ["Check Incoming Signal"],                     "Step 2 (Check Incoming Signal)"),
    ("connect_patch",  ["Connect Your S-Patch"],                      "Step 1 (Patch Serial Number)"),
    ("cannot_find",    ["Cannot find your S-Patch"],                  "Error: Cannot Find S-Patch (950)"),
    ("reset_patch",    ["Reset your S-Patch"],                        "Error: Reset S-Patch (963)"),
    ("no_study",       ["No Study Information", "No study information"], "Error: No Study Information"),
    ("bt_disabled",    ["Bluetooth not enabled"],                     "Error: Bluetooth Disabled"),
    ("upload",         ["Upload"],                                    "Upload Screen"),
]


def detect_current_screen(drv, timeout: int = 1) -> tuple:
    """
    Detect which AK app screen is currently shown.
    Returns (screen_id, human_readable_label).
    screen_id is 'unknown' if nothing matches.
    """
    for screen_id, texts, label in _SCREEN_SIGNATURES:
        for text in texts:
            if drv.is_visible_text(text, timeout=timeout):
                return screen_id, label
    return "unknown", "Unknown Screen"


def _capture_diagnostics(drv, tag: str):
    """Capture screenshot + current activity for diagnostics. Best-effort."""
    try:
        drv.screenshot(tag)
    except Exception as e:
        log.debug("[diag] screenshot failed: %s", e)
    try:
        activity = drv.drv.current_activity
        package  = drv.drv.current_package
        log.info("[diag] %s — activity=%s pkg=%s", tag, activity, package)
    except Exception as e:
        log.debug("[diag] activity query failed: %s", e)


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

    State-driven: detects current screen on every loop iteration and acts accordingly.
    Takes diagnostic screenshots on repeated BLE failures and on timeout.
    """
    # Bring the AK app to foreground first
    try:
        pkg = drv.cfg.get("app_package")
        if pkg:
            drv.drv.activate_app(pkg)
            time.sleep(1.5)
    except Exception:
        pass

    # Already on main screen
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

    serial = drv.cfg.get("test_serial_number", "")

    # Initial serial entry if input field is present
    try:
        el = drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")
        el.clear()
        el.send_keys(serial)
        time.sleep(0.5)
        log.info("[go_to_main] Serial entered: %s", serial)
    except Exception:
        log.info("[go_to_main] No EditText — connecting directly with registered device")

    if drv.is_visible_text("Connect", timeout=5, contains=False):
        try:
            drv.tap_text("Connect", timeout=5, contains=False)
        except Exception:
            pass
    else:
        log.info("[go_to_main] No Connect button visible — proceeding to wait loop")

    log.info("[go_to_main] Waiting up to %ds for main screen (serial: %s)", wait_ble, serial)

    _start_ts       = time.monotonic()
    _last_screen_id = None
    _connect_attempts  = 0
    _ble_error_count   = 0
    # How many times we've seen "Connect Your S-Patch" after the initial connect
    _DIAG_AFTER_N_RETRIES = 2   # take screenshot on 2nd retry
    _SLOW_RETRY_AFTER_N   = 4   # slow down retries after this many failures

    deadline = time.monotonic() + wait_ble

    while time.monotonic() < deadline:
        elapsed = int(time.monotonic() - _start_ts)
        screen_id, screen_label = detect_current_screen(drv, timeout=1)

        # Log every screen change
        if screen_id != _last_screen_id:
            log.info("[go_to_main] Detected screen: %s (%ds elapsed)", screen_label, elapsed)
            _last_screen_id = screen_id

        # ── SUCCESS ──────────────────────────────────────────────────────────
        if screen_id == "log_symptoms":
            log.info("[go_to_main] Main measurement screen reached (%ds elapsed)", elapsed)
            return

        # ── START STUDY ───────────────────────────────────────────────────────
        elif screen_id == "start_study":
            try:
                drv.tap_text("Start Study", timeout=5, contains=False)
                time.sleep(2)
            except Exception:
                pass

        # ── STEP 3: Review Study Setting ──────────────────────────────────────
        elif screen_id == "review_setting":
            time.sleep(1)
            try:
                drv.tap_text("Continue", timeout=5, contains=True)
                time.sleep(1)
            except Exception as e:
                log.warning("[go_to_main] Step 3 Continue tap failed: %s", e)

        # ── STEP 2: Check Incoming Signal ─────────────────────────────────────
        elif screen_id == "check_signal":
            time.sleep(2)  # allow Continue button to become interactive
            try:
                drv.tap_text("Continue", timeout=5, contains=True)
                time.sleep(1)
            except Exception as e:
                log.warning("[go_to_main] Step 2 Continue tap failed: %s", e)

        # ── STEP 1: Patch Serial Number (Connect Your S-Patch) ────────────────
        elif screen_id == "connect_patch":
            _connect_attempts += 1
            log.info("[go_to_main] Step 1 — Connect attempt #%d (%ds elapsed)",
                     _connect_attempts, elapsed)

            # Capture diagnostics on repeated failures
            if _connect_attempts == _DIAG_AFTER_N_RETRIES:
                log.warning("[go_to_main] BLE not connecting after %d attempts — capturing diagnostics",
                            _connect_attempts)
                _capture_diagnostics(drv, f"go_to_main_ble_retry_{_connect_attempts}")

            if _connect_attempts > _SLOW_RETRY_AFTER_N:
                log.warning("[go_to_main] Repeated BLE failure (%d attempts) — "
                            "patch may be out of range or not powered on", _connect_attempts)
                _capture_diagnostics(drv, f"go_to_main_ble_stuck_{_connect_attempts}")
                time.sleep(5)  # give patch more time before next attempt

            try:
                el = drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")
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

        # ── BLE ERROR: Cannot find your S-Patch (950) ────────────────────────
        elif screen_id == "cannot_find":
            _ble_error_count += 1
            log.warning("[go_to_main] BLE error 950 (cannot find patch) — count: %d", _ble_error_count)
            if _ble_error_count == 2:
                _capture_diagnostics(drv, "go_to_main_ble_error_950")
            try:
                drv.tap_text(["OK", "Ok"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(2)

        # ── BLE ERROR: Reset your S-Patch (963) ──────────────────────────────
        elif screen_id == "reset_patch":
            _ble_error_count += 1
            log.warning("[go_to_main] BLE error 963 (reset patch) — count: %d", _ble_error_count)
            if _ble_error_count == 2:
                _capture_diagnostics(drv, "go_to_main_ble_error_963")
            try:
                drv.tap_text(["OK", "Ok"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(2)

        # ── No Study Information popup ────────────────────────────────────────
        elif screen_id == "no_study":
            log.warning("[go_to_main] No Study Information popup → dismissing")
            try:
                drv.tap_text(["Confirm", "Ok", "OK"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(1)

        # ── Bluetooth disabled popup ──────────────────────────────────────────
        elif screen_id == "bt_disabled":
            log.warning("[go_to_main] Bluetooth not enabled popup → dismissing")
            try:
                drv.tap_text(["Ok", "OK"], timeout=3, contains=False)
            except Exception:
                pass
            time.sleep(1)

        # ── Unknown screen ────────────────────────────────────────────────────
        else:
            time.sleep(1)

    # ── TIMEOUT — capture full diagnostics ───────────────────────────────────
    elapsed_total = int(time.monotonic() - _start_ts)
    final_screen_id, final_screen_label = detect_current_screen(drv, timeout=2)

    log.error("[go_to_main] TIMEOUT after %ds — current screen: %s", elapsed_total, final_screen_label)
    _capture_diagnostics(drv, "go_to_main_timeout")

    try:
        activity = drv.drv.current_activity
        package  = drv.drv.current_package
    except Exception:
        activity = "unknown"
        package  = "unknown"

    raise Exception(
        f"Main screen not reached after {wait_ble}s\n"
        f"  Current screen:   {final_screen_label}\n"
        f"  Connect attempts: {_connect_attempts}\n"
        f"  BLE errors:       {_ble_error_count}\n"
        f"  Activity:         {activity}\n"
        f"  Package:          {package}\n"
        f"  Expected:         Log Symptoms (Main Screen)\n"
        f"  Action:           Check patch power, BLE range, and study status"
    )


def _is_menu_open(drv, timeout: int = 2) -> bool:
    """Return True if any known menu-indicator text is visible."""
    indicators = ["Setting", "Settings", "Version Information", "Guide", "Patch Placement"]
    for text in indicators:
        if drv.is_visible_text(text, timeout=timeout):
            return True
    return False


def open_menu(drv, wait: float = 2.0):
    """
    Open the hamburger/gear menu on the Step 1 screen.

    Tries multiple strategies in priority order:
      1. content-desc 'Open navigation drawer' or 'Menu'
      2. ImageButton instance 0 (first button)
      3. ImageButton instance 1 (second button)
      4. Coordinate fallbacks at common positions
    """
    # Capture screen state before first attempt for diagnostics
    try:
        drv.screenshot("open_menu_before")
    except Exception:
        pass

    # All tap strategies to try per attempt
    def _try_tap() -> bool:
        # Strategy 1: content-description (most reliable across devices)
        for desc in ["Open navigation drawer", "Menu", "Open menu", "Navigation"]:
            try:
                el = drv.drv.find_element(
                    AppiumBy.ACCESSIBILITY_ID, desc
                )
                el.click()
                return True
            except Exception:
                pass

        # Strategy 2: ImageButton in top 25% of screen (avoids bottom nav bar buttons)
        try:
            h = drv.drv.get_window_size()["height"]
            top_threshold = int(h * 0.25)
            els = drv.drv.find_elements(
                AppiumBy.ANDROID_UIAUTOMATOR,
                'new UiSelector().className("android.widget.ImageButton")'
            )
            for el in els:
                try:
                    loc = el.location
                    if loc["y"] < top_threshold:
                        el.click()
                        log.info("[open_menu] ImageButton at (%d,%d) clicked", loc["x"], loc["y"])
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # Strategy 3: coordinate fallbacks — right side (gear icon) and left side (hamburger)
        try:
            size = drv.drv.get_window_size()
            w, h = size["width"], size["height"]
            for pct_x, pct_y, label in [
                (0.915, 0.096, "top-right"),
                (0.085, 0.096, "top-left"),
                (0.915, 0.060, "top-right-high"),
                (0.085, 0.060, "top-left-high"),
            ]:
                x, y = int(w * pct_x), int(h * pct_y)
                drv.drv.tap([(x, y)])
                log.info("[open_menu] Coordinate tap %s (%d,%d)", label, x, y)
                return True
        except Exception:
            pass

        return False

    for attempt in range(3):
        _try_tap()
        time.sleep(wait)
        if _is_menu_open(drv, timeout=2):
            log.info("[open_menu] Menu opened on attempt %d", attempt + 1)
            return
        log.warning("[open_menu] Menu did not open (attempt %d/3)", attempt + 1)
        try:
            drv.screenshot(f"open_menu_fail_{attempt + 1}")
        except Exception:
            pass
        time.sleep(0.5)

    # Final diagnostic before raising
    try:
        drv.screenshot("open_menu_failed_final")
    except Exception:
        pass
    raise Exception(
        "open_menu: failed to open menu after 3 attempts. "
        "Check screenshot open_menu_failed_final — menu button may have moved or "
        "'Setting' text may have changed in the current app version."
    )


def close_menu(drv):
    drv.drv.press_keycode(4)
    time.sleep(0.5)
