"""
TC-SN (iOS): Serial Number Input Screen Regression Tests

Verified facts for this React Native app (iPhone 13 mini, iOS 18.6.2):
  - The UI is ONE flattened XCUIElementTypeOther container; the TextField and
    Connect button are NOT exposed as individual elements.
  - Typing: tapping XCUIElementTypeKey elements (labels "0"-"9", "Delete")
    fires real key events → React Native onChangeText updates correctly.
    mobile: type / typeText do NOT update RN state.
  - Reading the field: RN echoes the serial into the flattened container label
    as "Review Study Setting, S-Patch <value>," — parse page source for it.
  - Connect enabled state: not exposed via accessibility. Detect by pixel color
    of the button background: enabled = solid blue (51,122,169), disabled = white.
  - Keyboard "Done" button dismisses the numeric keyboard.
"""
import io
import re
import time
import logging

from appium.webdriver.common.appiumby import AppiumBy
from regression.helpers_ios import _ratio_tap, _is_keyboard_shown

log = logging.getLogger(__name__)

CONNECT_BUTTON_TEXT = "Connect"

# Ratio coordinates (fractions of screen size; verified on 375x812)
_INPUT_X   = 0.50
_INPUT_Y   = 0.296
_CONNECT_X = 0.50
_CONNECT_Y = 0.894   # Connect button center (verified via screenshot)

# Enabled Connect button color (verified): RGB(51, 122, 169)
def _is_blue(rgb) -> bool:
    r, g, b = rgb[:3]
    return b > r + 30 and b > 120 and r < 100


def _scan_connect_button_y(img):
    """
    Runtime calibration: scan the bottom band (y 82–97%) for a solid blue
    full-width button row. Robust to layout shifts across app versions.
    Returns the button-center y ratio, or None (button absent/disabled/white).
    """
    w, h = img.size
    for ry1000 in range(820, 970, 5):
        ry = ry1000 / 1000
        y = int(h * ry)
        if _is_blue(img.getpixel((int(w * 0.3), y))) and \
           _is_blue(img.getpixel((int(w * 0.7), y))):
            y2 = int(h * (ry + 0.02))
            if y2 < h and _is_blue(img.getpixel((int(w * 0.3), y2))):
                return ry + 0.02
    return None


def _ensure_keyboard_up(drv) -> bool:
    """Tap the serial input area if keyboard is not already visible."""
    if _is_keyboard_shown(drv):
        return True
    _ratio_tap(drv, _INPUT_X, _INPUT_Y, "serial input activate")
    time.sleep(1.2)
    return _is_keyboard_shown(drv)


def _find_key(drv, label: str):
    """Find a keyboard key element by exact label. Labels: '0'-'9', 'Delete'."""
    try:
        els = drv.drv.find_elements(
            AppiumBy.IOS_PREDICATE,
            f'type == "XCUIElementTypeKey" AND label == "{label}"',
        )
        if els:
            return els[0]
    except Exception:
        pass
    return None


def _tap_key(drv, char: str) -> bool:
    """Tap a single key on the numeric keyboard. Returns False if key not present."""
    el = _find_key(drv, char)
    if el is None:
        return False
    try:
        el.click()
        return True
    except Exception:
        # Element went stale — re-find once
        el = _find_key(drv, char)
        if el is None:
            return False
        el.click()
        return True


def _dismiss_keyboard(drv):
    """Dismiss the numeric keyboard via its Done button."""
    try:
        els = drv.drv.find_elements(
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeButton" AND label == "Done"',
        )
        if els:
            els[0].click()
            time.sleep(0.8)
            return
    except Exception:
        pass
    try:
        drv.drv.hide_keyboard()
        time.sleep(0.8)
        return
    except Exception:
        pass
    _ratio_tap(drv, 0.933, 0.575, "Done (keyboard dismiss)")
    time.sleep(0.8)


def _type_via_keys(drv, text: str) -> bool:
    """Type text by tapping keyboard keys. Only digits exist on this keyboard."""
    success = True
    for char in text:
        if not _tap_key(drv, char):
            log.debug("[sn-ios] Key '%s' not on keyboard (blocked)", char)
            success = False
        time.sleep(0.1)
    return success


def _clear_input(drv, max_chars: int = 8):
    """Clear the field by tapping the Delete key (label 'Delete', capital D)."""
    _ensure_keyboard_up(drv)
    for _ in range(max_chars):
        if not _tap_key(drv, "Delete"):
            log.warning("[sn-ios] Delete key not found — cannot clear")
            return
        time.sleep(0.06)


def _type_serial(drv, text: str, dismiss: bool = True):
    """Enter serial via keyboard key taps; optionally dismiss keyboard after."""
    _ensure_keyboard_up(drv)
    _type_via_keys(drv, text)
    time.sleep(0.3)
    if dismiss:
        _dismiss_keyboard(drv)


def _get_input_value(drv) -> str:
    """
    Read the serial field value from React Native state.
    RN echoes the input into the flattened container label:
    "Review Study Setting, S-Patch <value>, Registered Study, ..."
    """
    try:
        src = drv.drv.page_source
        m = re.search(r"Review Study Setting, S-Patch ([^,]*),", src)
        if m:
            return m.group(1).strip()
    except Exception as e:
        log.warning("[sn-ios] _get_input_value page_source error: %s", e)
    return ""


def _is_connect_enabled(drv) -> bool:
    """
    Detect Connect button enabled state via pixel scan (runtime-calibrated).
    Enabled = solid blue full-width band found in the bottom area;
    disabled = white with light border (no blue band).
    Keyboard must be dismissed (it covers the button).
    """
    if _is_keyboard_shown(drv):
        _dismiss_keyboard(drv)
    try:
        from PIL import Image
        png = drv.drv.get_screenshot_as_png()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        y_found = _scan_connect_button_y(img)
        log.debug("[sn-ios] Connect scan: %s", y_found)
        return y_found is not None
    except Exception as e:
        log.warning("[sn-ios] Connect pixel check failed: %s", e)
        return False


def _tap_connect(drv):
    """Tap the Connect button (scan-calibrated coordinate tap)."""
    if _is_keyboard_shown(drv):
        _dismiss_keyboard(drv)
    y = _CONNECT_Y
    try:
        from PIL import Image
        png = drv.drv.get_screenshot_as_png()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        y = _scan_connect_button_y(img) or _CONNECT_Y
    except Exception:
        pass
    _ratio_tap(drv, _CONNECT_X, y, "Connect button")


def _dismiss_popup(drv):
    """Dismiss the 950 error popup. Tries native alert, then labels, then coords."""
    # Native UIAlertController
    try:
        drv.drv.execute_script("mobile: alert", {"action": "accept"})
        time.sleep(0.5)
        return
    except Exception:
        pass
    # Button element with common labels
    for label in ("Ok", "OK", "확인", "Close", "Dismiss"):
        try:
            els = drv.drv.find_elements(AppiumBy.IOS_PREDICATE, f'label == "{label}"')
            for el in els:
                size = el.size
                if size["width"] * size["height"] < 100_000:
                    el.click()
                    time.sleep(0.5)
                    return
        except Exception:
            pass
    # RN modal fallback: save screenshot for coordinate discovery, tap center-bottom of modal
    try:
        drv.screenshot("popup_dismiss_fallback")
    except Exception:
        pass
    _ratio_tap(drv, 0.50, 0.60, "popup OK (fallback)")
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# Test Cases (same TC IDs as Android version)
# ---------------------------------------------------------------------------

def test_sn_002_empty_connect_disabled(drv, runner):
    """TC-SN-002 | Empty input → Connect button disabled"""
    _clear_input(drv)
    _dismiss_keyboard(drv)
    runner.assert_false(_is_connect_enabled(drv), "Connect button should be disabled when empty")


def test_sn_003_partial_connect_state(drv, runner):
    """TC-SN-003 | 5-digit input → observe Connect button state"""
    _type_serial(drv, "12345")
    enabled = _is_connect_enabled(drv)
    if enabled:
        log.warning("TC-SN-003 (iOS): Connect enabled with 5 digits — no client-side length validation")
    else:
        log.info("TC-SN-003 (iOS): Connect disabled for 5 digits")
    _clear_input(drv)
    _dismiss_keyboard(drv)


def test_sn_004_over_limit(drv, runner):
    """TC-SN-004 | 7+ digit input → blocked at 6 or button disabled"""
    _type_serial(drv, "1234567")
    actual = _get_input_value(drv)
    log.info("TC-SN-004 (iOS): field value after typing 7 digits = '%s' (len=%d)", actual, len(actual))
    if len(actual) > 6:
        runner.assert_false(_is_connect_enabled(drv), "Connect should be disabled for 7 digits")
    _clear_input(drv)
    _dismiss_keyboard(drv)


def test_sn_005_non_numeric_state(drv, runner):
    """TC-SN-005 | Letter input → numeric keyboard has no letter keys (blocked)"""
    _ensure_keyboard_up(drv)
    typed = _type_via_keys(drv, "ABCDEF")
    actual = _get_input_value(drv)
    alpha_chars = [c for c in actual if c.isalpha()]
    if alpha_chars:
        enabled = _is_connect_enabled(drv)
        if enabled:
            log.warning("TC-SN-005 (iOS): Letters accepted and Connect enabled")
        else:
            log.info("TC-SN-005 (iOS): Letters accepted but Connect disabled")
        _clear_input(drv)
    else:
        log.info("TC-SN-005 (iOS): Keyboard blocked letter input")
    _dismiss_keyboard(drv)


def test_sn_001_valid_6digits_connect_enabled(drv, runner):
    """TC-SN-001 | 6-digit number input → Connect button enabled"""
    _type_serial(drv, "123456")
    value = _get_input_value(drv)
    log.info("TC-SN-001 (iOS): field value = '%s'", value)
    runner.assert_true(_is_connect_enabled(drv), "Connect button should be enabled (6 digits)")
    _clear_input(drv)
    _dismiss_keyboard(drv)


def test_sn_008_keyboard_dismiss_retain(drv, runner):
    """TC-SN-008 | Enter 3 digits then dismiss keyboard → input value retained"""
    _type_serial(drv, "123", dismiss=False)
    _dismiss_keyboard(drv)
    time.sleep(0.5)
    actual = _get_input_value(drv)
    runner.assert_true("123" in actual, f"Input lost after dismissing keyboard (got '{actual}')")
    _clear_input(drv)
    _dismiss_keyboard(drv)


def test_sn_007_wrong_serial_950_popup(drv, runner):
    """TC-SN-007 | Wrong serial (112233) → Connect → 950 popup appears"""
    _type_serial(drv, "112233")
    runner.assert_true(_is_connect_enabled(drv), "Connect not enabled for 6-digit serial")
    _tap_connect(drv)
    popup_visible = drv.is_visible_text("Cannot find your S-Patch", timeout=60)
    _dismiss_popup(drv)
    time.sleep(1)
    _clear_input(drv)
    _dismiss_keyboard(drv)
    runner.assert_true(popup_visible, "950 popup not shown for wrong serial (112233)")


def test_sn_009_wrong_serial_950_popup_timing(drv, runner):
    """TC-SN-009 | Wrong serial → Connect → measure time until 950 popup"""
    _type_serial(drv, "112233")
    if not _is_connect_enabled(drv):
        runner.assert_true(False, "Connect not enabled for 6-digit serial — cannot test timing")
        return
    _tap_connect(drv)
    t_start = time.monotonic()
    popup_visible = False
    elapsed = -1.0
    for _ in range(120):
        time.sleep(0.5)
        if drv.is_visible_text("Cannot find your S-Patch", timeout=1):
            elapsed = round(time.monotonic() - t_start, 1)
            popup_visible = True
            break
    _dismiss_popup(drv)
    time.sleep(1)
    _clear_input(drv)
    _dismiss_keyboard(drv)
    if popup_visible:
        log.info("TC-SN-009 (iOS): 950 popup appeared in %.1fs", elapsed)
    runner.assert_true(popup_visible, "950 popup did not appear within 60s for wrong serial")
    if popup_visible:
        runner.assert_true(elapsed <= 60.0, f"950 popup too slow: {elapsed}s (expected ≤ 60s)")


TESTS = [
    test_sn_002_empty_connect_disabled,
    test_sn_003_partial_connect_state,
    test_sn_004_over_limit,
    test_sn_005_non_numeric_state,
    test_sn_001_valid_6digits_connect_enabled,
    test_sn_008_keyboard_dismiss_retain,
    test_sn_007_wrong_serial_950_popup,
    test_sn_009_wrong_serial_950_popup_timing,
]
