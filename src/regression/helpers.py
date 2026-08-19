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
    ("start_study",    ["Start Study"],                                        "Start Study Screen"),
    ("log_symptoms",   ["Log Symptoms", "My Study Progress", "Device Status"], "Main Screen (Study Running)"),
    ("review_setting", ["Review Study Setting"],                      "Step 3 (Review Study Setting)"),
    ("check_signal",   ["Check Incoming Signal"],                     "Step 2 (Check Incoming Signal)"),
    ("connect_patch",  ["Connect Your S-Patch"],                      "Step 1 (Patch Serial Number)"),
    ("cannot_find",    ["Cannot find your S-Patch"],                  "Error: Cannot Find S-Patch (950)"),
    ("reset_patch",    ["Reset your S-Patch"],                        "Error: Reset S-Patch (963)"),
    ("no_study",       ["No Study Information", "No study information"], "Error: No Study Information"),
    ("bt_disabled",    ["Bluetooth not enabled"],                     "Error: Bluetooth Disabled"),
    ("side_menu",      ["Version Information", "Terms and Information"], "Side Menu (Settings)"),
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


def _click_clickable_in_region(drv, x_min: float, x_max: float,
                               y_min: float, y_max: float,
                               classes: tuple = ("android.widget.Button",
                                                 "android.widget.ImageButton",
                                                 "android.widget.ImageView",
                                                 "android.view.View",
                                                 "android.view.ViewGroup")) -> bool:
    """
    Bounds-based fallback (same pattern as open_menu Strategy 2): find a
    clickable element whose center lies inside the given screen-ratio region
    and click it. Clicking the found element — not a blind coordinate — keeps
    this device/aspect-ratio independent. Returns True when something was
    clicked.
    """
    try:
        size = drv.drv.get_window_size()
        w, h = size["width"], size["height"]
        for cls in classes:
            els = drv.drv.find_elements(
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().className("{cls}").clickable(true)')
            for el in els:
                try:
                    loc = el.location
                    sz = el.size
                    cx = loc["x"] + sz["width"] / 2
                    cy = loc["y"] + sz["height"] / 2
                    if x_min * w <= cx <= x_max * w and y_min * h <= cy <= y_max * h:
                        el.click()
                        log.info("[bounds-fallback] %s center=(%d,%d) clicked",
                                 cls, cx, cy)
                        return True
                except Exception:
                    pass
    except Exception as e:
        log.debug("[bounds-fallback] region search failed: %s", e)
    return False


def _tap_bottom_button(drv, label: str, timeout: int = 5) -> None:
    """Tap a full-width bottom action button: text locator → bounds search in
    the bottom band → ratio coordinate as last resort."""
    try:
        drv.tap_text(label, timeout=timeout, contains=False)
        return
    except Exception as e:
        log.warning("[go_to_main] '%s' locator tap failed; using bottom-button fallback: %s", label, e)

    # Bounds fallback: clickable element centered in the bottom band
    # (works on any aspect ratio / nav-bar configuration)
    if _click_clickable_in_region(drv, x_min=0.2, x_max=0.8, y_min=0.78, y_max=0.97):
        return

    # Last resort: ratio coordinate observed on Pixel 7
    size = drv.drv.get_window_size()
    x = int(size["width"] * 0.5)
    y = int(size["height"] * 0.895)
    drv.drv.tap([(x, y)])


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
                # Appium-Python-Client 4.0+ removed start_activity() --
                # reuse AndroidDriver's compat shim (execute_script
                # "mobile: startActivity"), same fix as driver.py
                # (2026-08-19: an unguarded call here raised AttributeError
                # and crashed the run outright).
                drv._start_activity_compat(pkg, act)
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


def go_to_main(drv, wait_ble: int = 240):
    """App initial screen → Connect → (auto-handle Step 2/3/Start Study) → main measurement screen.

    State-driven: detects current screen on every loop iteration and acts accordingly.
    Takes diagnostic screenshots on repeated BLE failures and on timeout.

    wait_ble was 120s until a real run on a Samsung SM-A325N (Android 11)
    timed out stuck on the Start Study screen -- the tap itself was landing
    fine (text-based locator, not a coordinate issue) but the actual
    Start-Study BLE/backend handshake was slower on this device than the
    old budget allowed for (2026-08-11).
    """
    # Bring the AK app to foreground first
    try:
        pkg = drv.cfg.get("app_package")
        if pkg:
            drv.drv.activate_app(pkg)
            time.sleep(1.5)
    except Exception:
        pass

    # Already on main screen — but only if "Start Study" is NOT visible.
    # The pre-study screen (before tapping Start Study) also shows "My Study Progress" and
    # "Device Status" alongside the "Start Study" button — must not mistake it for the main screen.
    if not drv.is_visible_text("Start Study", timeout=1, contains=False):
        for _indicator in ["Log Symptoms", "My Study Progress", "Device Status"]:
            if drv.is_visible_text(_indicator, timeout=3):
                log.info("[go_to_main] Already on main screen (%s visible)", _indicator)
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
                _tap_bottom_button(drv, "Start Study", timeout=5)
                time.sleep(2)
            except Exception as e:
                log.warning("[go_to_main] Start Study tap failed: %s", e)

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

        # ── Side menu left open (e.g. a prior run was killed mid app-log-
        # capture, which navigates into this exact screen) ──────────────────
        elif screen_id == "side_menu":
            log.warning("[go_to_main] Side menu open (likely leftover from a prior "
                        "run's interrupted log capture) → closing")
            try:
                close_menu(drv)
            except Exception as e:
                log.warning("[go_to_main] close_menu() failed: %s", e)
            time.sleep(0.5)

        # ── Unknown screen — try to dismiss dialogs / permission popups ─────
        else:
            # Try common dialog buttons first (permissions, ToS, onboarding)
            _dismissed = False
            for btn in ["Allow", "ALLOW", "OK", "Ok", "확인", "동의", "Agree", "Skip", "SKIP"]:
                try:
                    if drv.is_visible_text(btn, timeout=1, contains=False):
                        drv.tap_text(btn, timeout=2, contains=False)
                        log.info("[go_to_main] Unknown screen — dismissed via '%s'", btn)
                        _dismissed = True
                        time.sleep(1)
                        break
                except Exception:
                    pass
            if not _dismissed:
                time.sleep(1)

    # ── TIMEOUT — capture full diagnostics ───────────────────────────────────
    elapsed_total = int(time.monotonic() - _start_ts)
    final_screen_id, final_screen_label = detect_current_screen(drv, timeout=2)

    # Screen reached main just at deadline — treat as success
    if final_screen_id == "log_symptoms":
        log.info("[go_to_main] Main screen reached at deadline (%ds elapsed) — accepting", elapsed_total)
        return

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
    indicators = [
        "Setting", "Settings", "Version Information", "Guide", "Patch Placement",
        "Terms and Information", "Live Streaming", "Privacy", "About",
    ]
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
    # Bring app to foreground (handles case where app was sent home by extra Back press)
    try:
        pkg = drv.cfg.get("app_package")
        if pkg:
            drv.drv.activate_app(pkg)
            time.sleep(1.0)
    except Exception:
        pass

    if _is_menu_open(drv, timeout=1):
        log.info("[open_menu] Menu already open")
        return

    # Capture screen state before first attempt for diagnostics
    try:
        drv.screenshot("open_menu_before")
    except Exception as e:
        # Silently-swallowed screenshot failures previously left zero
        # evidence when open_menu failed (code review 2026-07-22 incident:
        # 3 TCs failed with none of the expected diagnostic screenshots on
        # disk, so root cause — likely a brief Appium/UiAutomator2 session
        # hiccup — couldn't be confirmed after the fact). Log it instead.
        log.warning("[open_menu] screenshot 'open_menu_before' failed: %s", e)

    # All tap strategies to try per attempt
    def _try_tap() -> bool:
        # Strategy 1: content-description (most reliable across devices)
        for desc in ["Open navigation drawer", "Menu", "Open menu", "Navigation",
                     "Settings", "More options", "More"]:
            try:
                el = drv.drv.find_element(AppiumBy.ACCESSIBILITY_ID, desc)
                el.click()
                log.info("[open_menu] content-desc '%s' clicked", desc)
                return True
            except Exception:
                pass

        # Strategy 2: ImageButton or View in top 15% of screen, right half (gear icon area)
        try:
            size = drv.drv.get_window_size()
            w, h = size["width"], size["height"]
            top_threshold = int(h * 0.15)
            right_threshold = int(w * 0.5)
            for cls in ["android.widget.ImageButton", "android.widget.ImageView",
                        "android.view.View", "android.view.ViewGroup"]:
                els = drv.drv.find_elements(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().className("{cls}").clickable(true)'
                )
                for el in els:
                    try:
                        loc = el.location
                        if loc["y"] < top_threshold and loc["x"] > right_threshold:
                            el.click()
                            log.info("[open_menu] %s at (%d,%d) clicked", cls, loc["x"], loc["y"])
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        # Strategy 3: coordinate fallbacks — percentage-based (device-independent)
        try:
            size = drv.drv.get_window_size()
            w, h = size["width"], size["height"]
            for pct_x, pct_y, label in [
                (0.92, 0.07, "top-right"),
                (0.92, 0.05, "top-right-high"),
                (0.85, 0.07, "top-right-mid"),
                (0.08, 0.07, "top-left"),
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
        try:
            drv.screenshot(f"open_menu_after_tap_{attempt + 1}")
        except Exception as e:
            log.warning("[open_menu] screenshot 'open_menu_after_tap_%d' failed: %s", attempt + 1, e)
        if _is_menu_open(drv, timeout=2):
            log.info("[open_menu] Menu opened on attempt %d", attempt + 1)
            return
        log.warning("[open_menu] Menu did not open (attempt %d/3)", attempt + 1)
        try:
            drv.screenshot(f"open_menu_fail_{attempt + 1}")
        except Exception as e:
            log.warning("[open_menu] screenshot 'open_menu_fail_%d' failed: %s", attempt + 1, e)
        time.sleep(0.5)

    # Last resort before declaring failure: the 3 tap attempts above assume
    # the Appium session itself was healthy throughout. If it briefly
    # dropped (2026-07-22 incident: menu was actually open on screen but
    # every is_visible_text check still returned False, with screenshot
    # capture also silently failing — a classic dead-session signature),
    # recover it and give the check one more chance instead of failing a
    # suite over a transient hiccup unrelated to real app behavior.
    try:
        drv.ensure_session()
        if _is_menu_open(drv, timeout=2):
            log.info("[open_menu] Menu was open after session recovery — treating as success")
            return
    except Exception as e:
        log.warning("[open_menu] session recovery check failed: %s", e)

    # Final diagnostic before raising
    try:
        drv.screenshot("open_menu_failed_final")
    except Exception as e:
        log.warning("[open_menu] screenshot 'open_menu_failed_final' failed: %s", e)
    device_info = ""
    try:
        info = drv.get_device_info()
        device_info = (
            f"\n  Device: {info.get('manufacturer', '?')} {info.get('model', '?')}"
            f" Android {info.get('android_version', '?')}"
        )
    except Exception:
        pass
    activity_info = ""
    try:
        activity_info = f"\n  Activity: {drv.drv.current_package}/{drv.drv.current_activity}"
    except Exception:
        pass
    raise Exception(
        "open_menu: failed to open menu after 3 attempts. "
        "Check screenshot open_menu_failed_final — menu button may have moved or "
        f"'Setting' text may have changed in the current app version."
        f"{device_info}{activity_info}"
    )


def _menu_closed_ok(drv) -> bool:
    """
    True once the menu is closed onto a legitimate main screen — Step 1
    ("Connect Your S-Patch", pre-BLE) OR the active-study main screen. Before
    this, close_menu() only recognized Step 1, so a study-in-progress caller
    (menu_study.py) never saw success and kept pressing Back for all 4
    attempts, risking navigating further than intended (code review
    2026-07-22). Only widens the existing Step 1 check — doesn't change it.
    """
    if drv.is_visible_text("Connect Your S-Patch", timeout=1):
        return True
    active_indicator = drv.sel.get("symptom_add_text", "Log Symptoms")
    return drv.is_visible_text(active_indicator, timeout=1)


def close_menu(drv):
    for attempt in range(4):
        if _menu_closed_ok(drv):
            return

        if _is_menu_open(drv, timeout=1):
            # Current Android app shows a home/close icon at the top-right of
            # the menu screen. Back can be swallowed on some sub-states, so tap
            # the visible close affordance first, then fall back to Back.
            try:
                # Bounds fallback first: clickable icon in the top-right zone
                if not _click_clickable_in_region(drv, x_min=0.78, x_max=1.0,
                                                  y_min=0.02, y_max=0.18):
                    # Last resort: ratio coordinate observed on Pixel 7
                    size = drv.drv.get_window_size()
                    drv.drv.tap([(int(size["width"] * 0.91), int(size["height"] * 0.105))])
                time.sleep(0.8)
                if _menu_closed_ok(drv):
                    return
            except Exception:
                pass

        try:
            drv.drv.press_keycode(4)
        except Exception:
            pass
        time.sleep(0.8)

    if _is_menu_open(drv, timeout=1):
        log.warning("[close_menu] Menu still open after close attempts")
