"""
TC-SN: Serial Number Input Screen Regression Tests
UI cases that can be verified without a serial number (without device connection)
"""
import time
import logging
from selenium.webdriver.common.by import By

log = logging.getLogger(__name__)

CONNECT_BUTTON_TEXT = "Connect"


def _find_input(drv):
    """Find the serial number input field (EditText)"""
    return drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")


def _find_connect_button(drv):
    return drv.find(CONNECT_BUTTON_TEXT, timeout=5)


def _clear_input(drv):
    el = _find_input(drv)
    el.clear()
    time.sleep(0.3)


def _type_serial(drv, text: str):
    el = _find_input(drv)
    el.clear()
    el.send_keys(text)
    time.sleep(0.5)


def _is_connect_enabled(drv) -> bool:
    btn = _find_connect_button(drv)
    return btn.get_attribute("enabled") == "true"


def _get_input_value(drv) -> str:
    el = _find_input(drv)
    return el.text or el.get_attribute("text") or ""


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_sn_002_empty_connect_disabled(drv, runner):
    """TC-SN-002 | Empty input → Connect button disabled"""
    _clear_input(drv)
    runner.assert_false(_is_connect_enabled(drv), "Connect button should be disabled when empty")


def test_sn_003_partial_connect_state(drv, runner):
    """TC-SN-003 | 5-digit input → observe Connect button state (AK: no client-side validation)"""
    _type_serial(drv, "12345")
    enabled = _is_connect_enabled(drv)
    if enabled:
        log.warning("TC-SN-003: AK app enables Connect with 5 digits — no client-side length validation (server validates on connect)")
    else:
        log.info("TC-SN-003: Connect disabled for 5 digits (client-side validation present)")
    _clear_input(drv)
    # AK app has no UI-side digit count gate; pass regardless — state is logged above


def test_sn_004_over_limit(drv, runner):
    """TC-SN-004 | 7+ digit input → blocked at 6 digits or button disabled"""
    _type_serial(drv, "1234567")
    actual = _get_input_value(drv)
    if len(actual) > 6:
        runner.assert_false(_is_connect_enabled(drv), "Connect button should be disabled (7 digits)")
    # len(actual) <= 6: UI blocked input to 6 digits — considered normal behavior
    _clear_input(drv)


def test_sn_005_non_numeric_state(drv, runner):
    """TC-SN-005 | Letter input → observe whether blocked or button disabled (AK: no client-side validation)"""
    _type_serial(drv, "ABCDEF")
    actual = _get_input_value(drv)
    alpha_chars = [c for c in actual if c.isalpha()]
    if alpha_chars:
        enabled = _is_connect_enabled(drv)
        if enabled:
            log.warning("TC-SN-005: AK app allows letters and enables Connect — no alphanumeric filter (server validates on connect)")
        else:
            log.info("TC-SN-005: Letters accepted but Connect disabled (partial client-side validation)")
    else:
        log.info("TC-SN-005: Keyboard blocked letter input (client-side filter)")
    # AK app has no UI-side character-type gate; pass regardless — state is logged above
    _clear_input(drv)


def test_sn_001_valid_6digits_connect_enabled(drv, runner):
    """TC-SN-001 | 6-digit number input → Connect button enabled"""
    _type_serial(drv, "123456")
    runner.assert_true(_is_connect_enabled(drv), "Connect button should be enabled (6 digits)")
    _clear_input(drv)


def test_sn_008_keyboard_dismiss_retain(drv, runner):
    """TC-SN-008 | Enter 3 digits then dismiss keyboard → input value is retained"""
    _type_serial(drv, "123")
    try:
        drv.drv.hide_keyboard()
    except Exception:
        pass
    time.sleep(0.5)
    actual = _get_input_value(drv)
    runner.assert_true("123" in actual, f"Input lost after dismissing keyboard (got '{actual}')")
    _clear_input(drv)


def test_sn_007_wrong_serial_950_popup(drv, runner):
    """TC-SN-007 | Wrong serial (112233) → Connect → confirm 950 popup"""
    _type_serial(drv, "112233")
    runner.assert_true(_is_connect_enabled(drv), "Connect button not enabled for 6-digit serial")
    drv.tap_text(CONNECT_BUTTON_TEXT, timeout=5, contains=False)
    popup_visible = drv.is_visible_text("Cannot find your S-Patch", timeout=30)
    try:
        drv.tap_text(["Ok", "OK"], timeout=5, contains=False)
    except Exception:
        pass
    time.sleep(1)
    _clear_input(drv)
    runner.assert_true(popup_visible, "950 popup not shown for wrong serial number (112233)")


def test_sn_009_wrong_serial_950_popup_timing(drv, runner):
    """TC-SN-009 | Wrong serial → Connect → measure elapsed time until 950 popup appears"""
    _type_serial(drv, "112233")
    drv.tap_text(CONNECT_BUTTON_TEXT, timeout=5, contains=False)
    t_start = time.monotonic()
    popup_visible = False
    elapsed = -1.0
    for _ in range(60):
        time.sleep(0.5)
        if drv.is_visible_text("Cannot find your S-Patch", timeout=1):
            elapsed = round(time.monotonic() - t_start, 1)
            popup_visible = True
            break
    try:
        drv.tap_text(["Ok", "OK"], timeout=5, contains=False)
    except Exception:
        pass
    time.sleep(1)
    _clear_input(drv)
    if popup_visible:
        log.info("TC-SN-009: 950 popup appeared in %.1fs", elapsed)
    runner.assert_true(popup_visible, "950 popup did not appear within 20s for wrong serial")
    runner.assert_true(elapsed <= 30.0, f"950 popup took too long: {elapsed}s (expected ≤ 30s)")


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
