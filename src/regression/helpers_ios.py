"""
iOS navigation helpers — mirrors helpers.py interface for IOSDriver.

NEW FILE — does not modify src/regression/helpers.py (Android) in any way.

Locator fallback order (per user requirement):
  1. Accessibility ID / name / label
  2. iOS Class Chain
  3. iOS Predicate String
  4. Ratio-based coordinate tap (ONLY when React Native flattens accessibility tree)

React Native note: this app collapses the entire UI into one XCUIElementTypeOther
accessible container, so locator-based strategies return 0 elements.
Coordinate tap is the reliable fallback and uses screen-size ratios (not pixel values)
so it works across iPhone SE / standard / Pro Max screen sizes.
"""
import time
import logging
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By

log = logging.getLogger(__name__)

# ── Per-screen coordinate constants (ratio-based, not absolute pixels) ───────
# All values are fractions of screen width/height.
# iPhone 13 mini reference: 375×812 pt → these ratios work on any iPhone size.

# Step 1 — Connect Your S-Patch
_SERIAL_INPUT_X  = 0.50   # center horizontally
_SERIAL_INPUT_Y  = 0.296  # serial number text field (~y=240 on 375×812)

_CONNECT_BTN_X   = 0.50   # center horizontally
_CONNECT_BTN_Y   = 0.930  # "Connect" button at bottom (~y=755 on 375×812)

# Step 2 / Step 3 / Start Study — all share the same bottom-button position
_CONTINUE_BTN_X  = 0.50   # center horizontally
_CONTINUE_BTN_Y  = 0.930  # "Continue" / "Start Study" button (~y=755 on 375×812)

# Log Symptoms sheet — submit button
_SUBMIT_BTN_X    = 0.50   # center horizontally
_SUBMIT_BTN_Y    = 0.880  # "Save" / submit button inside sheet (~y=715 on 375×812)


# ── Screen signatures ────────────────────────────────────────────────────────
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


def _ratio_tap(drv, x_ratio: float, y_ratio: float, label: str = ""):
    """
    Tap at a screen-size-ratio position.
    x_ratio / y_ratio are fractions of screen width/height (0.0 – 1.0).
    Works across all iPhone screen sizes since no absolute pixel values are used.
    Uses mobile: tap (XCUITest native) which is more reliable than the deprecated tap() API.
    """
    def _tap_once():
        size = drv.drv.get_window_size()
        x = int(size["width"]  * x_ratio)
        y = int(size["height"] * y_ratio)
        log.info("[tap-ios] Coordinate tap%s at (%d, %d) [%.1f%% x, %.1f%% y] on %dx%d screen",
                 f" ({label})" if label else "",
                 x, y, x_ratio * 100, y_ratio * 100, size["width"], size["height"])
        # mobile: tap uses XCUITest native gesture (more reliable in xcuitest 11+)
        try:
            drv.drv.execute_script("mobile: tap", {"x": float(x), "y": float(y)})
            return
        except Exception as e:
            log.debug("[tap-ios] mobile:tap failed (%s) — falling back to tap()", e)
        drv.drv.tap([(x, y)])

    last_exc = None
    for attempt in range(1, 4):
        try:
            _tap_once()
            return
        except Exception as e:
            last_exc = e
            if not hasattr(drv, "_is_session_error") or not drv._is_session_error(e):
                raise
            log.warning("[tap-ios] session error during coordinate tap%s — reconnecting (%d/3): %s",
                        f" ({label})" if label else "", attempt, e)
            try:
                drv.reporter.log_event("session_lost_ios", {
                    "reason": "coordinate_tap_failed",
                    "label": label,
                    "attempt": attempt,
                    "error": str(e),
                })
            except Exception:
                pass
            drv.reconnect()
            try:
                drv.wait_idle(2.0)
            except Exception:
                time.sleep(2.0)
    raise last_exc


def _try_tap_element(drv, text: str, timeout: int = 3) -> bool:
    """
    Try locator-based tap in priority order:
      1. Accessibility ID
      2. iOS Class Chain
      3. iOS Predicate String (exact only — CONTAINS risks matching the whole-screen container)
      4. XPath (last resort)
    Skips elements that cover >80% of the screen (whole-screen container false match).
    Returns True if a real element was tapped, False if all locators failed.
    """
    locators = [
        # 1. Accessibility ID / name / label
        (AppiumBy.ACCESSIBILITY_ID, text, "AccessibilityID"),
        # 2. iOS Class Chain — button type only
        (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeButton[`label == "{text}"`]', "ClassChain-exact"),
        (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeButton[`label CONTAINS "{text}"`]', "ClassChain-contains"),
        # 3. iOS Predicate — exact match only (avoid CONTAINS on container)
        (AppiumBy.IOS_PREDICATE, f'label == "{text}"', "Predicate-exact"),
        # 4. XPath
        (By.XPATH, f'//*[@label="{text}" or @name="{text}" or @value="{text}"]', "XPath"),
    ]
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    try:
        screen = drv.drv.get_window_size()
        screen_area = screen["width"] * screen["height"]
    except Exception:
        screen_area = 375 * 812

    for by, selector, strategy in locators:
        try:
            el = WebDriverWait(drv.drv, min(timeout, 2)).until(
                EC.presence_of_element_located((by, selector))
            )
            # Skip elements that cover >80% of screen — likely the whole-screen container
            try:
                el_area = el.size["width"] * el.size["height"]
                if el_area > screen_area * 0.8:
                    log.debug("[tap-ios] '%s' via %s covers %.0f%% of screen — skipping (container)",
                              text, strategy, el_area / screen_area * 100)
                    continue
            except Exception:
                pass
            el.click()
            log.info("[tap-ios] '%s' found via %s", text, strategy)
            return True
        except Exception:
            pass

    log.debug("[tap-ios] '%s' not found via any locator — will use coordinate fallback", text)
    return False


def _try_visible_text(drv, text: str, timeout: int = 2) -> bool:
    """
    Check if text is visible using locator priority order.
    Returns True if found via any strategy.
    """
    locators = [
        (AppiumBy.ACCESSIBILITY_ID, text),
        (AppiumBy.IOS_CLASS_CHAIN, f'**/XCUIElementTypeStaticText[`label == "{text}"`]'),
        (AppiumBy.IOS_PREDICATE,   f'label == "{text}" AND visible == true'),
        (By.XPATH,                 f'//*[@label="{text}" or @name="{text}"]'),
    ]
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    for by, selector in locators:
        try:
            WebDriverWait(drv.drv, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
            return True
        except Exception:
            pass
    return False


def _extract_spatch_serial(label: str) -> str:
    """
    Extract the S-Patch serial from the container label.
    Label format: "...Review Study Setting, S-Patch 510131, Registered Study..."
    Returns "" if serial is absent/empty.
    """
    import re
    m = re.search(r's-patch (\d+)', label)
    return m.group(1) if m else ""


def _active_step_from_pixels(drv):
    """
    Determine which stepper circle (1/2/3 at top of screen) is active.
    Active step = solid blue fill RGB≈(51,122,169); inactive = white w/ border.
    Runtime-calibrated: scans y 11–22% for the stepper row (robust to layout
    shifts across app versions); x≈27.2%/50%/72.4%. r<100 excludes the
    light-blue circle border (~145).
    Returns 1, 2, 3, or None if indeterminate (e.g. not on the stepper pager).
    """
    try:
        import io
        from PIL import Image
        png = drv.drv.get_screenshot_as_png()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size

        def _blue(px):
            r, g, b = px[:3]
            return b > r + 30 and b > 120 and r < 100

        for ry1000 in range(110, 225, 5):
            y = int(h * ry1000 / 1000)
            hits = [step for step, rx in ((1, 0.272), (2, 0.500), (3, 0.724))
                    if _blue(img.getpixel((int(w * rx), y)))]
            if len(hits) == 1:
                return hits[0]
    except Exception as e:
        log.debug("[detect-ios] stepper pixel check failed: %s", e)
    return None


def _detect_screen_from_container(drv) -> tuple:
    """
    For React Native apps with flattened accessibility tree:
    parse the single container's label to detect the current screen.

    Step detection strategy:
    - The stepper pager renders ALL steps in one accessible label always.
    - Step 1 is detected by the serial TextField (rarely exposed) or by the
      stepper-circle pixel check (active circle is solid blue).
    - Steps 2/3 are distinguished by S-Patch serial presence + stepper pixels.
    """
    # Step 1: uniquely identified by the serial input TextField being accessible.
    # NOTE: on this app the TextField is usually NOT exposed (flat tree), so
    # the pixel-based stepper check below is the reliable path.
    try:
        text_fields = drv.drv.find_elements(
            AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeTextField"'
        )
        if text_fields:
            return "connect_patch", "Step 1 (Patch Serial Number)"
    except Exception:
        pass

    # Parse accessible container label for all other screens
    try:
        containers = drv.drv.find_elements(AppiumBy.IOS_PREDICATE, "accessible == true")
        for el in containers:
            try:
                el_area = el.size["width"] * el.size["height"]
                if el_area < 10000:
                    continue
            except Exception:
                pass
            label = (el.get_attribute("label") or "").lower()
            if not label:
                continue

            # Error screens
            if "cannot find your s-patch" in label:
                return "cannot_find", "Error: Cannot Find S-Patch (950)"
            if "reset your s-patch" in label:
                return "reset_patch", "Error: Reset S-Patch (963)"
            if "no study information" in label:
                return "no_study", "Error: No Study Information"
            if "bluetooth not enabled" in label:
                return "bt_disabled", "Error: Bluetooth Disabled"

            # Main measurement screen
            if "add diary" in label or ("log symptoms" in label and "start study" not in label):
                return "log_symptoms", "Main Screen (Study Running)"

            # Start Study screen
            if "start study" in label and "registered study" in label:
                return "start_study", "Start Study Screen"

            # Steps 1/2/3 all show "review study setting" + "registered study"
            # in the flattened pager label. Serial populated → BLE connected
            # (Step 3). Serial empty is AMBIGUOUS between Step 1 (waiting for
            # input) and Step 2 (BLE scanning) — resolve via stepper pixels.
            if "review study setting" in label and "registered study" in label:
                serial = _extract_spatch_serial(label)
                if serial:
                    return "review_setting", f"Step 3 (Review Study Setting) serial={serial}"
                step = _active_step_from_pixels(drv)
                if step == 1:
                    return "connect_patch", "Step 1 (stepper pixel check)"
                if step == 3:
                    return "review_setting", "Step 3 (stepper pixel check)"
                return "check_signal", "Step 2 (BLE connecting — serial empty)"

            if "check incoming signal" in label:
                return "check_signal", "Step 2 (Check Incoming Signal)"

    except Exception:
        pass
    return "unknown", "Unknown Screen"


def detect_current_screen(drv, timeout: int = 1) -> tuple:
    """
    Detect current screen.
    For React Native apps with flattened accessibility tree,
    container label parsing is fast (1 element lookup vs 40+ WebDriverWait calls).
    Falls back to locator-based only when container returns unknown.
    """
    # 1. Fast path: container label parsing (single element lookup, ~0.5s)
    result = _detect_screen_from_container(drv)
    if result[0] != "unknown":
        return result

    # 2. Slow path: locator-based (use short timeout since container already failed)
    short = min(timeout, 0.5)
    for screen_id, texts, label in _SCREEN_SIGNATURES:
        for text in texts:
            if _try_visible_text(drv, text, timeout=short):
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


def _save_failure_diagnostics(drv, tag: str):
    """Full diagnostics on failure: screenshot + page source + device info."""
    _capture_diagnostics(drv, tag)
    try:
        page_src = drv.drv.page_source
        path = drv.artifacts.save_text(f"{tag}_pagesource.xml", page_src)
        log.warning("[diag-ios] Page source saved: %s", path)
    except Exception:
        pass
    try:
        info = drv.get_device_info()
        log.warning("[diag-ios] Device: %s iOS %s udid=%s",
                    info.get("model"), info.get("ios_version"), info.get("udid"))
    except Exception:
        pass


def ios_go_back(drv):
    """
    Navigate back on iOS. Sub-screens show a back arrow at top-left which is
    NOT an element in the flat RN tree — tap it by coordinate (verified
    ~9.8% x, ~10.5% y on 375x812). Replaces Android press_keycode(4).
    """
    _ratio_tap(drv, 0.098, 0.105, "back arrow (top-left)")
    time.sleep(1.0)


def close_sheet(drv):
    """
    Close a bottom sheet on iOS.
    Order: locator-based Done/Cancel → swipe-down gesture.
    """
    for btn in ["Done", "Cancel", "Close"]:
        if _try_tap_element(drv, btn, timeout=1):
            time.sleep(0.5)
            return
    # Swipe down to dismiss bottom sheet (ratio-based)
    try:
        size = drv.drv.get_window_size()
        w, h = size["width"], size["height"]
        # Swipe from 40% down to 80% down to dismiss sheet
        drv.drv.swipe(int(w * 0.5), int(h * 0.4), int(w * 0.5), int(h * 0.8), 300)
        time.sleep(0.5)
    except Exception:
        pass


def _clear_saved_app_state(udid: str, bundle_id: str) -> bool:
    """
    Delete iOS Saved Application State so the app launches fresh at Step 1
    instead of restoring the previous UI (BLE scanning on Step 2).
    Uses pymobiledevice3 HouseArrest AFC (no root needed).
    Returns True if cleared, False if failed.
    """
    import asyncio

    async def _do_clear():
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.house_arrest import HouseArrestService
        except ImportError:
            log.warning("[setup-ios] pymobiledevice3 not installed — cannot clear app state")
            return False

        try:
            lockdown = await create_using_usbmux(serial=udid)
            service = await HouseArrestService.create(lockdown, bundle_id)
        except Exception as e:
            log.warning("[setup-ios] HouseArrest connect failed: %s", e)
            return False

        state_base = (
            "/Library/Saved Application State"
            f"/{bundle_id}.savedState"
            "/KnownSceneSessions"
        )
        deleted = 0
        try:
            items = await service.listdir(state_base)
            for item in items:
                path = f"{state_base}/{item}"
                try:
                    await service.rm(path)
                    deleted += 1
                except Exception:
                    pass
            try:
                await service.rm(state_base)
                deleted += 1
            except Exception:
                pass
        except Exception:
            pass
        finally:
            try:
                await service.close()
            except Exception:
                pass

        if deleted:
            log.info("[setup-ios] Cleared %d saved-state file(s) — app will start fresh", deleted)
        else:
            log.info("[setup-ios] No saved state found (already clean)")
        return True

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_do_clear())
        loop.close()
        return result
    except Exception as e:
        log.warning("[setup-ios] _clear_saved_app_state failed: %s", e)
        return False


def reset_to_step1(drv, hard: bool = True):
    """
    Clear iOS Saved Application State, restart the app, confirm Step 1.

    Root cause of Step 2 resume: iOS restores the app's UI via
    KnownSceneSessions/data.data.  Deleting that file forces a fresh launch.

    Returns:
      True  — Step 1 confirmed (serial TextField found)
      False — Step 1 not reached; go_to_main() will handle navigation
    """
    bundle_id = drv.cfg.get("bundle_id", "")
    udid      = drv.cfg.get("udid", "")

    if hard:
        # 1. Terminate first so the state file is no longer locked by the process
        try:
            drv.drv.terminate_app(bundle_id)
        except Exception:
            pass
        time.sleep(1)

        # 2. Delete the saved UI state
        log.info("[setup-ios] Clearing Saved Application State for %s", bundle_id)
        _clear_saved_app_state(udid, bundle_id)

        # 3. Relaunch the app
        try:
            drv.drv.activate_app(bundle_id)
        except Exception:
            pass
        time.sleep(4)

    def _check_step1() -> bool:
        """Return True if we're on Step 1 (TextField found OR keyboard is open after tap)."""
        if _find_serial_input(drv):
            return True
        # Try tapping the serial input area to activate the field
        _ratio_tap(drv, _SERIAL_INPUT_X, _SERIAL_INPUT_Y, "activate serial input")
        time.sleep(1.5)
        if _find_serial_input(drv):
            return True
        # Keyboard open = field is focused = Step 1 is active
        if _is_keyboard_shown(drv):
            log.info("[setup-ios] Step 1 confirmed — keyboard open after tap")
            return True
        return False

    # Check immediately — app should start from Step 1 now
    if _check_step1():
        log.info("[setup-ios] Step 1 confirmed immediately")
        return True

    screen_id, _ = detect_current_screen(drv)
    if screen_id == "log_symptoms":
        log.info("[setup-ios] Already on main screen — skipping Step 1 reset")
        return False

    # App started on Step 2 BLE scan (no registered serial → ~90s natural timeout).
    # IMPORTANT: Do NOT tap during this wait — tapping on the BLE scan screen can
    # restart its internal timer, preventing the natural timeout from firing.
    # Just poll passively until the app returns to Step 1 on its own.
    log.info("[setup-ios] App on Step 2 BLE scan — waiting up to 150s for Step 1 (no taps)")
    deadline = time.monotonic() + 150
    _last_log = 0
    while time.monotonic() < deadline:
        # TextField: appears once BLE scan times out and app returns to Step 1
        if _find_serial_input(drv):
            elapsed = int(150 - (deadline - time.monotonic()))
            log.info("[setup-ios] Step 1 TextField appeared after %ds", elapsed)
            return True
        # Keyboard: visible if the field is already focused from a prior tap
        if _is_keyboard_shown(drv):
            elapsed = int(150 - (deadline - time.monotonic()))
            log.info("[setup-ios] Step 1 confirmed via keyboard (%ds elapsed)", elapsed)
            return True
        screen_id, _ = detect_current_screen(drv)
        if screen_id == "log_symptoms":
            log.info("[setup-ios] Main screen reached — skipping Step 1 reset")
            return False
        # If we're on connect_patch without TextField, try tapping to activate keyboard
        if screen_id == "connect_patch":
            if _check_step1():
                elapsed = int(150 - (deadline - time.monotonic()))
                log.info("[setup-ios] Step 1 reached (keyboard/TextField) after %ds", elapsed)
                return True
        now = time.monotonic()
        if now - _last_log >= 15:
            elapsed = int(150 - (deadline - now))
            log.info("[setup-ios] Waiting for Step 1 (%ds elapsed) — app on %s", elapsed, screen_id)
            _last_log = now
        time.sleep(5)

    log.warning("[setup-ios] Step 1 not reached after 150s — go_to_main will handle")
    return False


def _tap_serial_input(drv) -> bool:
    """
    Tap serial number input field.
    1. Locator: Accessibility ID / Class Chain / Predicate / XPath
    2. Fallback: ratio coordinate (center x, ~29.6% y = text field position)
    Returns True if found via locator, False if coordinate fallback was used.
    """
    # 1. Try locators
    for by, selector, label in [
        (AppiumBy.ACCESSIBILITY_ID, "Enter the Serial Number here.", "AccessibilityID-hint"),
        (AppiumBy.IOS_CLASS_CHAIN,  "**/XCUIElementTypeTextField", "ClassChain-TextField"),
        (AppiumBy.IOS_PREDICATE,    'type == "XCUIElementTypeTextField"', "Predicate-TextField"),
        (By.XPATH,                  "//XCUIElementTypeTextField", "XPath-TextField"),
    ]:
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            el = WebDriverWait(drv.drv, 2).until(EC.presence_of_element_located((by, selector)))
            el.click()
            log.info("[serial-ios] TextField found via %s", label)
            return True
        except Exception:
            pass

    # 2. Coordinate fallback — serial number input field (~29.6% down from top)
    _ratio_tap(drv, _SERIAL_INPUT_X, _SERIAL_INPUT_Y, "serial number input field")
    return False


def _tap_keyboard_key(drv, label: str) -> bool:
    """Tap a numeric-keyboard key by exact label ('0'-'9', 'Delete' — capital D)."""
    try:
        els = drv.drv.find_elements(
            AppiumBy.IOS_PREDICATE,
            f'type == "XCUIElementTypeKey" AND label == "{label}"',
        )
        if els:
            els[0].click()
            return True
    except Exception:
        pass
    return False


def _enter_serial(drv, serial: str) -> bool:
    """
    Enter serial number by tapping individual keyboard keys — the ONLY method
    that triggers React Native onChangeText on this app. send_keys / mobile: type
    update the UITextField display but NOT the RN JavaScript state, so the value
    is lost on re-render and Connect stays disabled.
    """
    if not _is_keyboard_shown(drv):
        _tap_serial_input(drv)
        time.sleep(1.0)
    if not _is_keyboard_shown(drv):
        log.warning("[serial-ios] Keyboard did not appear — cannot enter serial")
        return False

    # Clear any leftover content (Delete key label is capital-D "Delete")
    for _ in range(8):
        if not _tap_keyboard_key(drv, "Delete"):
            break
        time.sleep(0.05)

    ok = True
    for ch in serial:
        if not _tap_keyboard_key(drv, ch):
            log.warning("[serial-ios] Key '%s' not found on keyboard", ch)
            ok = False
        time.sleep(0.1)

    _dismiss_keyboard(drv)
    if ok:
        log.info("[serial-ios] Serial entered via keyboard key taps: %s", serial)
    return ok


def _dismiss_keyboard(drv):
    """
    Dismiss the iOS keyboard after text entry.
    1. Tap "Done" button (top-right of number keyboard, ~93% x, ~57% y)
    2. hide_keyboard() Appium method
    3. Tap outside keyboard area
    """
    # 1. Try "Done" button via locator
    if _try_tap_element(drv, "Done", timeout=2):
        time.sleep(0.5)
        log.info("[keyboard-ios] Dismissed via 'Done' button")
        return
    # 2. Appium hide_keyboard
    try:
        drv.drv.hide_keyboard()
        time.sleep(0.5)
        log.info("[keyboard-ios] Dismissed via hide_keyboard()")
        return
    except Exception:
        pass
    # 3. Tap Done button coordinate (~93% x, ~57% y on number keyboard)
    _ratio_tap(drv, 0.933, 0.575, "Done button (keyboard dismiss)")
    time.sleep(0.5)


def _is_keyboard_shown(drv) -> bool:
    """Return True if the iOS keyboard is currently visible."""
    try:
        if drv.drv.is_keyboard_shown():
            return True
    except Exception:
        pass
    try:
        kb_els = drv.drv.find_elements(AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeKeyboard"')
        if kb_els:
            return True
    except Exception:
        pass
    # Last resort: XCUIElementTypeKeyboard will appear in page source when keyboard is up
    try:
        if "XCUIElementTypeKeyboard" in drv.drv.page_source:
            return True
    except Exception:
        pass
    return False


def _find_serial_input(drv):
    """Find serial number text field element, or None if not accessible."""
    locators = [
        (AppiumBy.ACCESSIBILITY_ID, "Enter the Serial Number here."),
        (AppiumBy.IOS_CLASS_CHAIN,  "**/XCUIElementTypeTextField"),
        (AppiumBy.IOS_PREDICATE,    'type == "XCUIElementTypeTextField"'),
        (By.XPATH,                  "//XCUIElementTypeTextField"),
    ]
    for by, selector in locators:
        try:
            els = drv.drv.find_elements(by, selector)
            if els:
                return els[0]
        except Exception:
            pass
    return None


def _tap_bottom_button(drv, button_text: str, timeout: int = 5) -> bool:
    """
    Tap a navigation button (Connect / Continue / Start Study).
    1. Try all locator strategies first
    2. Fallback: ratio coordinate at bottom of screen (~93% y)
       — all main navigation buttons share this bottom position
    """
    # 1. Locator-based
    if _try_tap_element(drv, button_text, timeout=timeout):
        return True

    # 2. Coordinate fallback — bottom navigation button (Connect/Continue/Start Study)
    _ratio_tap(drv, _CONTINUE_BTN_X, _CONTINUE_BTN_Y,
               f"bottom button ({button_text})")
    return False


def go_to_step2(drv, wait_ble: int = 45):
    if not _try_visible_text(drv, "Connect Your S-Patch", timeout=5):
        raise Exception("Not on Step 1 screen — please call reset_to_step1() first")

    serial = drv.cfg.get("test_serial_number", "680150")
    el = _find_serial_input(drv)
    if el:
        try:
            el.clear()
            el.send_keys(serial)
            time.sleep(0.5)
        except Exception:
            _tap_serial_input(drv)
            time.sleep(0.3)
            try:
                drv.drv.send_keys(serial)
            except Exception:
                pass
    else:
        # Coordinate fallback: tap input, type serial
        _tap_serial_input(drv)
        time.sleep(0.5)
        try:
            drv.drv.send_keys(serial)
        except Exception:
            pass
        time.sleep(0.3)

    # Tap Connect button
    _tap_bottom_button(drv, "Connect", timeout=5)

    deadline = time.monotonic() + wait_ble
    while time.monotonic() < deadline:
        if _try_visible_text(drv, "Check Incoming Signal", timeout=2):
            return
        if _try_visible_text(drv, "Review Study Setting", timeout=1):
            raise Exception("Step 2 skipped — study is registered on web")
        time.sleep(1)
    raise Exception(f"Failed to enter Step 2 after {wait_ble}s")


def _is_menu_open(drv, timeout: int = 2) -> bool:
    # Menu-screen-unique texts. NOTE: do NOT use "Setting"/"Guide" — Step 1's
    # flattened label contains "Review Study Setting" and would false-positive.
    indicators = ["Live Streaming Duration", "Version Information",
                  "Patch Placement", "Terms and Information"]
    # Flat RN tree: menu texts live inside one big container label — exact-label
    # locators never match, so check the page source directly (single WDA call).
    try:
        src = drv.drv.page_source
        if any(t in src for t in indicators):
            return True
    except Exception:
        pass
    for text in indicators:
        if _try_visible_text(drv, text, timeout=timeout):
            return True
    return False


def open_menu(drv, wait: float = 2.0):
    """
    Open hamburger/settings menu.
    1. Accessibility ID (most reliable)
    2. iOS Class Chain — button in top 25% of screen
    3. iOS Predicate
    4. Coordinate fallback — top-right gear icon (~91.5% x, ~7% y)
    """
    try:
        drv.screenshot("open_menu_before_ios")
    except Exception:
        pass

    def _try_tap() -> bool:
        # 1. Accessibility ID
        for desc in ["Open navigation drawer", "Menu", "Open menu", "Navigation",
                     "Settings", "Setting"]:
            try:
                el = drv.drv.find_element(AppiumBy.ACCESSIBILITY_ID, desc)
                el.click()
                log.info("[open_menu-iOS] AccessibilityID '%s' clicked", desc)
                return True
            except Exception:
                pass

        # 2. iOS Class Chain — buttons in top 25% of screen
        try:
            h = drv.drv.get_window_size()["height"]
            top_threshold = int(h * 0.25)
            for chain in [
                "**/XCUIElementTypeButton",
                "**/XCUIElementTypeImage",
            ]:
                els = drv.drv.find_elements(AppiumBy.IOS_CLASS_CHAIN, chain)
                for el in els:
                    try:
                        loc = el.location
                        if loc["y"] < top_threshold:
                            el.click()
                            log.info("[open_menu-iOS] ClassChain %s at (%d,%d) clicked",
                                     chain, loc["x"], loc["y"])
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        # 3. iOS Predicate — button in top area
        try:
            els = drv.drv.find_elements(AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeButton"')
            h = drv.drv.get_window_size()["height"]
            for el in els:
                if el.location.get("y", 999) < int(h * 0.25):
                    el.click()
                    log.info("[open_menu-iOS] Predicate button in top area clicked")
                    return True
        except Exception:
            pass

        # 4. Coordinate fallback — gear icon top-right (~90.6% x, ~10.5% y,
        # measured from screenshot on 375x812: icon center ≈ (340, 86))
        _ratio_tap(drv, 0.906, 0.105, "menu/gear icon (top-right)")
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
        # Self-heal: app may be stuck on a sub-screen (Version Info, Patch
        # Placement) whose back arrow sits top-left. Harmless on Step 1.
        _ratio_tap(drv, 0.098, 0.105, "back arrow (escape sub-screen)")
        time.sleep(1.0)

    _save_failure_diagnostics(drv, "open_menu_failed_final_ios")
    device_info = ""
    try:
        info = drv.get_device_info()
        device_info = f"\n  Device: {info.get('model', '?')} iOS {info.get('ios_version', '?')}"
    except Exception:
        pass
    raise Exception(
        f"open_menu: failed after 3 attempts (iOS).{device_info}"
    )


def close_menu(drv):
    """
    Close the menu screen. On iOS this menu is a FULL SCREEN (not a drawer);
    the home icon at top-right (same spot as the gear icon) returns to Step 1.
    """
    _ratio_tap(drv, 0.906, 0.105, "home icon (close menu)")
    time.sleep(1.0)
    if not _is_menu_open(drv):
        return
    # Fallback: iOS back swipe
    try:
        size = drv.drv.get_window_size()
        drv.drv.swipe(int(size["width"] * 0.02), int(size["height"] * 0.5),
                      int(size["width"] * 0.5), int(size["height"] * 0.5), 300)
        time.sleep(1.0)
    except Exception:
        pass


def go_to_main(drv, wait_ble: int = 300):
    """
    Navigate to main measurement screen on iOS.
    Uses same state-machine as Android.
    Button tapping tries locators first, falls back to ratio coordinates.
    """
    try:
        bundle_id = drv.cfg.get("bundle_id", "")
        if bundle_id:
            drv.drv.activate_app(bundle_id)
            time.sleep(1.5)
    except Exception:
        pass

    # Already on main screen (but not on pre-study Start Study screen)
    if not _try_visible_text(drv, "Start Study", timeout=1):
        for indicator in ["Log Symptoms", "My Study Progress", "Device Status"]:
            if _try_visible_text(drv, indicator, timeout=3):
                log.info("[go_to_main-iOS] Already on main screen (%s visible)", indicator)
                return

    # A run can start (or restart, e.g. after a web-server re-attach) when
    # the study already completed — none of the main-screen indicators
    # above apply anymore, and this state machine has no other concept of
    # "Study Overview" (issue #18/#39-adjacent finding, 2026-07-31): without
    # this check, go_to_main spun in its screen-detection wait loop for the
    # full wait_ble timeout (up to 5 minutes) never recognizing the screen,
    # confirmed live against a real device already on Study Overview.
    if hasattr(drv, "_detect_study_completed") and drv._detect_study_completed():
        log.info("[go_to_main-iOS] Study already completed (Study Overview screen) — nothing to navigate to")
        return

    # Dismiss lingering popups
    for popup_text, btn in [("Cannot find your S-Patch", ["Ok", "OK"]),
                             ("Reset your S-Patch",       ["Ok", "OK"]),
                             ("Bluetooth not enabled",    ["Ok", "OK"]),
                             ("No Study Information",     ["Confirm", "Ok", "OK"]),
                             ("No study information",     ["Confirm", "Ok", "OK"])]:
        if _try_visible_text(drv, popup_text, timeout=1):
            log.info("[go_to_main-iOS] Dismissing popup: %s", popup_text)
            for b in btn:
                if _try_tap_element(drv, b, timeout=3):
                    time.sleep(0.5)
                    break

    serial = drv.cfg.get("test_serial_number", "")

    # Serial entry + initial Connect — only when actually on Step 1.
    # Use TextField presence (not text label) — the pager label always contains
    # all step text regardless of which step is active.
    if _find_serial_input(drv):
        log.info("[go_to_main-iOS] Step 1 detected (serial TextField found)")
        if serial:
            if _enter_serial(drv, serial):
                log.info("[go_to_main-iOS] Serial entered: %s", serial)
                time.sleep(0.3)
            else:
                log.warning("[go_to_main-iOS] Serial entry failed — proceeding anyway")
        else:
            log.info("[go_to_main-iOS] No serial configured — connecting directly")
        _tap_bottom_button(drv, "Connect", timeout=5)
    else:
        log.info("[go_to_main-iOS] Step 1 TextField not found — entering wait loop")

    log.info("[go_to_main-iOS] Waiting up to %ds for main screen", wait_ble)
    _start_ts          = time.monotonic()
    _last_screen_id    = None
    _connect_attempts  = 0
    _ble_error_count   = 0
    _step2_first_seen  = None   # tracks when we first entered BLE-wait state
    _DIAG_AFTER_N      = 2
    _SLOW_AFTER_N      = 4
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
            # Tap "Start Study" button — locators then coordinate
            _tap_bottom_button(drv, "Start Study", timeout=5)
            time.sleep(2)

        elif screen_id == "review_setting":
            time.sleep(3)
            _capture_diagnostics(drv, "review_setting_before_tap")
            # iOS: Step 3 bottom button is labeled "Connect" (Android uses "Continue")
            # Locator-based first; if that fails, sweep y positions to find the real button
            if not _try_tap_element(drv, "Connect", timeout=5):
                for _y in [0.91, 0.89, 0.93, 0.87, 0.85]:
                    log.info("[go_to_main-iOS] Step 3 Connect scan y=%.0f%%", _y * 100)
                    _ratio_tap(drv, 0.50, _y, f"Connect (y={_y:.0%})")
                    time.sleep(2)
                    _sid, _ = detect_current_screen(drv)
                    if _sid != "review_setting":
                        log.info("[go_to_main-iOS] Screen changed at y=%.0f%% — button found", _y * 100)
                        break
            time.sleep(1)

        elif screen_id == "check_signal":
            # Step 2: BLE scanning — S-Patch serial empty means not yet detected.
            # The pager label always contains Steps 2+3 text; serial presence = BLE connected.
            # Do NOT tap "Continue" here — Step 2 has no Continue button.
            # The app auto-advances to Step 3 once BLE connects.
            if _step2_first_seen is None:
                _step2_first_seen = time.monotonic()
            step2_wait = int(time.monotonic() - _step2_first_seen)
            log.info(
                "[go_to_main-iOS] BLE scan in progress (%ds) — ensure S-Patch %s is ON and nearby",
                step2_wait, serial or "device",
            )
            # Every 60s try the "View" button (may show device list for manual selection)
            if step2_wait > 0 and step2_wait % 60 < 6:
                if _try_tap_element(drv, "View", timeout=2):
                    log.info("[go_to_main-iOS] Tapped 'View' button on Step 2 (%ds)", step2_wait)
                    time.sleep(3)
            else:
                time.sleep(5)

        elif screen_id == "connect_patch":
            _connect_attempts += 1
            log.info("[go_to_main-iOS] Step 1 attempt #%d (%ds)", _connect_attempts, elapsed)
            if _connect_attempts == _DIAG_AFTER_N:
                _capture_diagnostics(drv, f"go_to_main_ios_ble_retry_{_connect_attempts}")
            if _connect_attempts > _SLOW_AFTER_N:
                log.warning("[go_to_main-iOS] Repeated BLE failure (%d attempts)", _connect_attempts)
                _capture_diagnostics(drv, f"go_to_main_ios_ble_stuck_{_connect_attempts}")
                time.sleep(5)
            if serial:
                _enter_serial(drv, serial)
                time.sleep(0.3)
            _tap_bottom_button(drv, "Connect", timeout=5)
            time.sleep(2)

        elif screen_id in ("cannot_find", "reset_patch"):
            _ble_error_count += 1
            log.warning("[go_to_main-iOS] BLE error (%s) count: %d", screen_id, _ble_error_count)
            _try_tap_element(drv, "OK", timeout=3) or _try_tap_element(drv, "Ok", timeout=3)
            time.sleep(2)

        elif screen_id in ("no_study", "bt_disabled"):
            _try_tap_element(drv, "Confirm", timeout=3) or \
            _try_tap_element(drv, "Ok", timeout=3) or \
            _try_tap_element(drv, "OK", timeout=3)
            time.sleep(1)

        else:
            drv.dismiss_unexpected_popups()
            # Unknown screen — likely a sub-screen (Version/Device/Study Info,
            # File Information). Tap its top-left back arrow to escape;
            # harmless on screens without one.
            _ratio_tap(drv, 0.098, 0.105, "back arrow (escape unknown screen)")
            time.sleep(1.5)

    # Timeout
    elapsed_total = int(time.monotonic() - _start_ts)
    final_screen_id, final_screen_label = detect_current_screen(drv, timeout=2)
    log.error("[go_to_main-iOS] TIMEOUT after %ds — screen: %s", elapsed_total, final_screen_label)
    _save_failure_diagnostics(drv, "go_to_main_ios_timeout")

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
