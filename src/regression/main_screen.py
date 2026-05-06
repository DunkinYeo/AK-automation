"""
TC-MAIN: 측정 메인 화면 Regression Tests
Study 시작 후 메인 측정 화면에서 검증 가능한 케이스들
"""
import time
import logging

from src.regression.helpers import go_to_main

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

_NO_STUDY_TEXT = "No study information"
_NO_STUDY_MSG  = "No study registered in web portal"


def test_main_000_study_registered(drv, runner):
    """Pre-check | 웹 등록 Study 존재 여부 확인"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=3):
        runner.fail(_NO_STUDY_MSG)


def test_main_001_sections_visible(drv, runner):
    """TC-MAIN-001 | Study Information / Live ECG Signal 섹션 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    runner.assert_true(
        drv.is_visible_text("Study Information"),
        "Study Information not visible"
    )
    runner.assert_true(
        drv.is_visible_text("Live ECG Signal"),
        "Live ECG Signal not visible"
    )


def test_main_002_status_icons_visible(drv, runner):
    """TC-MAIN-002 | Network / Bluetooth / Battery 아이콘 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    runner.assert_true(drv.is_visible_text("Network"), "Network icon not visible")
    runner.assert_true(drv.is_visible_text("Bluetooth"), "Bluetooth icon not visible")
    runner.assert_true(drv.is_visible_text("Battery"), "Battery icon not visible")


def test_main_003_study_progress_visible(drv, runner):
    """TC-MAIN-003 | Study Progress 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    runner.assert_true(
        drv.is_visible_text("Study Progress"),
        "Study Progress not visible"
    )


def test_main_004_view_button_tap(drv, runner):
    """TC-MAIN-004 | View 버튼 탭 → ECG 상세 화면 진입"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    drv.tap_text("View", timeout=5)
    time.sleep(1.5)
    visible = (
        drv.is_visible_text("Live ECG", timeout=3)
        or drv.is_visible_text("ECG", timeout=2)
        or drv.is_visible_text("Live Streaming", timeout=2)
    )
    drv.drv.press_keycode(4)
    time.sleep(1)
    runner.assert_true(visible, "ECG detail screen not opened after View tap")


def test_main_005_add_diary_button_visible(drv, runner):
    """TC-MAIN-005 | Add Diary 버튼 표시 및 활성화"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    btn = drv.find("Add Diary", timeout=5)
    runner.assert_true(btn is not None, "Add Diary button not visible")
    runner.assert_true(
        btn.get_attribute("enabled") == "true",
        "Add Diary button is disabled"
    )


def test_main_006_back_blocked(drv, runner):
    """TC-MAIN-006 | 뒤로가기 → 메인 화면 유지 (이전 화면 이동 불가)"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    drv.drv.press_keycode(4)
    time.sleep(1.5)
    # 토스트는 Android 특성상 Appium 감지 불가 — 화면 이탈 여부로 검증
    runner.assert_true(
        drv.is_visible_text("Study Information", timeout=3),
        "Back button left main screen"
    )
    runner.assert_false(
        drv.is_visible_text("Connect Your S-Patch", timeout=2),
        "Back button navigated to Step 1"
    )


TESTS = [
    test_main_000_study_registered,
    test_main_001_sections_visible,
    test_main_002_status_icons_visible,
    test_main_003_study_progress_visible,
    test_main_004_view_button_tap,
    test_main_005_add_diary_button_visible,
    test_main_006_back_blocked,
]
