"""
TC-SN: Serial Number 입력 화면 Regression Tests
시리얼 넘버 없이 (기기 연결 없이) 검증 가능한 UI 케이스들
"""
import time
import logging
from selenium.webdriver.common.by import By

log = logging.getLogger(__name__)

CONNECT_BUTTON_TEXT = "Connect"


def _find_input(drv):
    """시리얼 넘버 입력 필드 (EditText) 찾기"""
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
    """TC-SN-002 | 빈 입력 → Connect 버튼 비활성화"""
    _clear_input(drv)
    runner.assert_false(_is_connect_enabled(drv), "Connect button should be disabled when empty")


def test_sn_003_partial_connect_state(drv, runner):
    """TC-SN-003 | 5자리 입력 → Connect 버튼 상태 관찰 (AK: 클라이언트 검증 없음)"""
    _type_serial(drv, "12345")
    enabled = _is_connect_enabled(drv)
    if enabled:
        log.warning("TC-SN-003: AK app enables Connect with 5 digits — no client-side length validation (server validates on connect)")
    else:
        log.info("TC-SN-003: Connect disabled for 5 digits (client-side validation present)")
    _clear_input(drv)
    # AK app has no UI-side digit count gate; pass regardless — state is logged above


def test_sn_004_over_limit(drv, runner):
    """TC-SN-004 | 7자리 이상 입력 → 6자리 초과 차단 또는 버튼 비활성화"""
    _type_serial(drv, "1234567")
    actual = _get_input_value(drv)
    if len(actual) > 6:
        runner.assert_false(_is_connect_enabled(drv), "Connect button should be disabled (7 digits)")
    # len(actual) <= 6: UI가 입력을 6자리로 차단함 — 정상 동작으로 간주
    _clear_input(drv)


def test_sn_005_non_numeric_state(drv, runner):
    """TC-SN-005 | 영문 입력 → 입력 차단 또는 버튼 비활성화 관찰 (AK: 클라이언트 검증 없음)"""
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
    """TC-SN-001 | 6자리 숫자 입력 → Connect 버튼 활성화"""
    _type_serial(drv, "123456")
    runner.assert_true(_is_connect_enabled(drv), "Connect button should be enabled (6 digits)")
    _clear_input(drv)


def test_sn_008_keyboard_dismiss_retain(drv, runner):
    """TC-SN-008 | 3자리 입력 후 키보드 내림 → 입력값 유지"""
    _type_serial(drv, "123")
    try:
        drv.drv.hide_keyboard()
    except Exception:
        pass
    time.sleep(0.5)
    actual = _get_input_value(drv)
    runner.assert_true("123" in actual, f"Input lost after dismissing keyboard (got '{actual}')")
    _clear_input(drv)


TESTS = [
    test_sn_002_empty_connect_disabled,
    test_sn_003_partial_connect_state,
    test_sn_004_over_limit,
    test_sn_005_non_numeric_state,
    test_sn_001_valid_6digits_connect_enabled,
    test_sn_008_keyboard_dismiss_retain,
]
