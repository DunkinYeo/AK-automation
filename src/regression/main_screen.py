"""
TC-MAIN: 측정 메인 화면 Regression Tests (AK)
Start Study 이후 메인 측정 화면에서 검증 가능한 케이스들
"""
import time
import logging

log = logging.getLogger(__name__)

_MAIN_TEXT    = "My Study Progress"
_LOG_SYMPTOMS = "Log Symptoms"
_START_STUDY  = "Start Study"


def _not_started(drv) -> bool:
    return drv.is_visible_text(_START_STUDY, timeout=2)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_main_000_study_started(drv, runner):
    """Pre-check | 스터디 시작 여부 확인 (Start Study 버튼 미표시)"""
    if _not_started(drv):
        runner.fail("Study not started — 'Start Study' button still visible")


def test_main_001_sections_visible(drv, runner):
    """TC-MAIN-001 | My Study Progress / Device Status 탭 표시"""
    if _not_started(drv):
        return
    runner.assert_true(drv.is_visible_text(_MAIN_TEXT), "My Study Progress not visible")
    runner.assert_true(drv.is_visible_text("Device Status"), "Device Status tab not visible")
    runner.assert_true(drv.is_visible_text("Real-time ECG"), "Real-time ECG tab not visible")


def test_main_002_status_cards_visible(drv, runner):
    """TC-MAIN-002 | Network / Bluetooth / Battery 카드 표시"""
    if _not_started(drv):
        return
    runner.assert_true(drv.is_visible_text("Network"), "Network card not visible")
    runner.assert_true(drv.is_visible_text("Bluetooth"), "Bluetooth card not visible")
    runner.assert_true(drv.is_visible_text("Battery"), "Battery card not visible")


def test_main_003_log_symptoms_button(drv, runner):
    """TC-MAIN-003 | Log Symptoms 버튼 표시 및 활성화"""
    if _not_started(drv):
        return
    btn = drv.find(_LOG_SYMPTOMS, timeout=5)
    runner.assert_true(btn is not None, "Log Symptoms button not visible")
    runner.assert_true(
        btn.get_attribute("enabled") == "true",
        "Log Symptoms button is disabled"
    )


def test_main_004_realtime_ecg_tab(drv, runner):
    """TC-MAIN-004 | Real-time ECG 탭 전환 → Live ECG Signal 표시"""
    if _not_started(drv):
        return
    drv.tap_text("Real-time ECG", timeout=5)
    time.sleep(1.5)
    visible = drv.is_visible_text("Live ECG Signal", timeout=5)
    # Device Status 탭으로 복귀
    drv.tap_text("Device Status", timeout=5)
    time.sleep(0.5)
    runner.assert_true(visible, "Live ECG Signal not visible on Real-time ECG tab")


def test_main_005_back_blocked(drv, runner):
    """TC-MAIN-005 | 뒤로가기 → 메인 화면 유지"""
    if _not_started(drv):
        return
    drv.drv.press_keycode(4)
    time.sleep(1.5)
    runner.assert_true(
        drv.is_visible_text(_LOG_SYMPTOMS, timeout=3),
        "Back button left main screen"
    )
    runner.assert_false(
        drv.is_visible_text("Connect Your S-Patch", timeout=2),
        "Back button navigated to Step 1"
    )


TESTS = [
    test_main_000_study_started,
    test_main_001_sections_visible,
    test_main_002_status_cards_visible,
    test_main_003_log_symptoms_button,
    test_main_004_realtime_ecg_tab,
    test_main_005_back_blocked,
]
