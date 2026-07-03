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
    """
    size = drv.drv.get_window_size()
    x = int(size["width"]  * x_ratio)
    y = int(size["height"] * y_ratio)
    log.info("[tap-ios] Coordinate tap%s at (%d, %d) [%.1f%% x, %.1f%% y] on %dx%d screen",
             f" ({label})" if label else "",
             x, y, x_ratio * 100, y_ratio * 100, size["width"], size["height"])
    drv.drv.tap([(x, y)])


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


def _detect_screen_from_container(drv) -> tuple:
    """
    For React Native apps with flattened accessibility tree:
    parse the single container's label to detect the current screen.

    Step detection strategy:
    - The stepper always shows 1/2/3 text + ALL step content in its label
    - UNIQUE identifiers per screen:
        Main  : "add diary" (only shown when study is active)
        Start : "start study" at the END of the label (button text)
        Step 3: "review study setting" + "registered study" (no "start study" button yet)
        Step 2: "check incoming signal" but NOT "review study setting"
        Step 1: "connect your s-patch" + ends with "connect" (the button)
    """
    try:
        containers = drv.drv.find_elements(AppiumBy.IOS_PREDICATE, "accessible == true")
        for el in containers:
            try:
                el_area = el.size["width"] * el.size["height"]
                # Only look at large elements (the main content container)
                if el_area < 10000:
                    continue
            except Exception:
                pass
            label = (el.get_attribute("label") or "").lower()
            if not label:
                continue

            # Error screens (unique text, check first)
            if "cannot find your s-patch" in label:
                return "cannot_find", "Error: Cannot Find S-Patch (950)"
            if "reset your s-patch" in label:
                return "reset_patch", "Error: Reset S-Patch (963)"
            if "no study information" in label:
                return "no_study", "Error: No Study Information"
            if "bluetooth not enabled" in label:
                return "bt_disabled", "Error: Bluetooth Disabled"

            # Main measurement screen: "add diary" only appears after study starts
            if "add diary" in label or ("log symptoms" in label and "start study" not in label):
                return "log_symptoms", "Main Screen (Study Running)"

            # Start Study screen: "start study" appears as a button AFTER step 3
            if "start study" in label and "registered study" in label:
                return "start_study", "Start Study Screen"

            # Step 3: Review Study Setting visible, study registered, no Start Study yet
            if "review study setting" in label and "registered study" in label:
                return "review_setting", "Step 3 (Review Study Setting)"

            # Step 2: Check Incoming Signal is visible
            if "check incoming signal" in label and "review study setting" not in label:
                return "check_signal", "Step 2 (Check Incoming Signal)"

            # Step 1: Connect Your S-Patch
            if "connect your s-patch" in label:
                return "connect_patch", "Step 1 (Patch Serial Number)"

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
            if _try_visible_text(drv, "Connect Your S-Patch", timeout=2):
                break
            try:
                size = drv.drv.get_window_size()
                # Left-edge swipe right = iOS back gesture
                drv.drv.swipe(int(size["width"] * 0.02), int(size["height"] * 0.5),
                               int(size["width"] * 0.5),  int(size["height"] * 0.5), 300)
            except Exception:
                pass
            time.sleep(0.8)


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


def _enter_serial(drv, serial: str) -> bool:
    """
    Enter serial number into the input field.
    Tries multiple strategies to type text on iOS:
      1. Find element → send_keys (if element accessible)
      2. Tap coordinate → re-find focused element → send_keys
      3. Tap coordinate → mobile: typeIntoTextField (Appium XCUITest command)
      4. Tap coordinate → keyboard action keys
    """
    # 1. Find element directly and type
    el = _find_serial_input(drv)
    if el:
        try:
            el.clear()
            el.send_keys(serial)
            log.info("[serial-ios] Serial entered via element.send_keys: %s", serial)
            _dismiss_keyboard(drv)
            return True
        except Exception as e:
            log.debug("[serial-ios] element.send_keys failed: %s", e)

    # 2. Tap coordinate to focus, then try to find element again
    _tap_serial_input(drv)
    time.sleep(0.8)  # wait for keyboard to appear
    el = _find_serial_input(drv)
    if el:
        try:
            el.clear()
            el.send_keys(serial)
            log.info("[serial-ios] Serial entered via focus+find+send_keys: %s", serial)
            return True
        except Exception:
            pass

    # 3. Appium XCUITest: mobile: type (types into currently focused element)
    try:
        drv.drv.execute_script("mobile: type", {"text": serial})
        log.info("[serial-ios] Serial entered via mobile:type: %s", serial)
        _dismiss_keyboard(drv)
        return True
    except Exception as e:
        log.debug("[serial-ios] mobile:type failed: %s", e)

    # 4. Appium XCUITest: mobile: typeIntoTextField
    try:
        drv.drv.execute_script("mobile: typeIntoTextField", {"text": serial})
        log.info("[serial-ios] Serial entered via mobile:typeIntoTextField: %s", serial)
        _dismiss_keyboard(drv)
        return True
    except Exception as e:
        log.debug("[serial-ios] mobile:typeIntoTextField failed: %s", e)

    # 5. Send keys to driver (types into focused element via W3C actions)
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(drv.drv).send_keys(serial).perform()
        log.info("[serial-ios] Serial entered via ActionChains.send_keys: %s", serial)
        _dismiss_keyboard(drv)
        return True
    except Exception as e:
        log.debug("[serial-ios] ActionChains.send_keys failed: %s", e)

    log.warning("[serial-ios] All text entry methods failed for serial: %s", serial)
    return False


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
    indicators = ["Setting", "Settings", "Version Information", "Guide", "Patch Placement"]
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

        # 4. Coordinate fallback — gear icon top-right (~91.5% x, ~7% y)
        _ratio_tap(drv, 0.915, 0.070, "menu/gear icon (top-right)")
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
    """Close menu via left-edge swipe (iOS back gesture)."""
    try:
        size = drv.drv.get_window_size()
        # Swipe from right to left to close side menu
        drv.drv.swipe(int(size["width"] * 0.5), int(size["height"] * 0.5),
                      int(size["width"] * 0.02), int(size["height"] * 0.5), 300)
        time.sleep(0.5)
    except Exception:
        pass


def go_to_main(drv, wait_ble: int = 120):
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

    # Serial entry on Step 1
    if serial:
        if _enter_serial(drv, serial):
            log.info("[go_to_main-iOS] Serial entered: %s", serial)
            time.sleep(0.3)
        else:
            log.warning("[go_to_main-iOS] Serial entry failed — proceeding anyway")
    else:
        log.info("[go_to_main-iOS] No serial configured — connecting directly")

    # Tap Connect button (locators → coordinate fallback)
    _tap_bottom_button(drv, "Connect", timeout=5)

    log.info("[go_to_main-iOS] Waiting up to %ds for main screen", wait_ble)
    _start_ts       = time.monotonic()
    _last_screen_id = None
    _connect_attempts  = 0
    _ble_error_count   = 0
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

        elif screen_id in ("review_setting", "check_signal"):
            time.sleep(2)
            # Tap "Continue" button — locators then coordinate
            _tap_bottom_button(drv, "Continue", timeout=5)
            time.sleep(1)

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
            time.sleep(1)

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
