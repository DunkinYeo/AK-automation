"""
TC-MENU-STUDY: 검사 진행 중 햄버거 메뉴 Regression Tests
Step 1 메뉴와 달리 Device Information / Study Information 항목이 추가됨
"""
import time
import logging

from src.regression.helpers import open_menu, close_menu

log = logging.getLogger(__name__)

_NO_STUDY_TEXT = "No study information"


def test_menu_study_000_study_registered(drv, runner):
    """TC-MENU-STUDY-000 | Pre-check: study registered"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=3):
        runner.fail("No study registered in web portal")


def test_menu_study_001_device_info_visible(drv, runner):
    """TC-MENU-STUDY-001 | 검사 중 메뉴 → Device Information 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    open_menu(drv, wait=2.5)
    try:
        runner.assert_true(
            drv.is_visible_text("Device Information", timeout=3),
            "Device Information not visible in menu during study"
        )
    finally:
        close_menu(drv)


def test_menu_study_002_study_info_visible(drv, runner):
    """TC-MENU-STUDY-002 | 검사 중 메뉴 → Study Information 항목 표시 (메뉴 내)"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    open_menu(drv, wait=2.0)
    try:
        # 메인 화면의 "Study Information" 섹션과 구분 위해 메뉴 내 위치 확인
        runner.assert_true(drv.is_visible_text("Version Information", timeout=3), "Menu did not open")
        runner.assert_true(
            drv.is_visible_text("Study Information", timeout=3),
            "Study Information not visible in menu during study"
        )
    finally:
        close_menu(drv)


def test_menu_study_003_sections_visible(drv, runner):
    """TC-MENU-STUDY-003 | 검사 중 메뉴 섹션 항목 정상 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    open_menu(drv, wait=2.5)
    try:
        runner.assert_true(drv.is_visible_text("Setting", timeout=3), "Setting not visible")
        runner.assert_true(drv.is_visible_text("Terms and Information", timeout=3), "Terms and Information not visible")
        runner.assert_true(drv.is_visible_text("Guide", timeout=3), "Guide not visible")
        runner.assert_true(drv.is_visible_text("Version Information", timeout=3), "Version Information not visible")
        runner.assert_true(drv.is_visible_text("Patch Placement", timeout=3), "Patch Placement not visible")
    finally:
        close_menu(drv)


def test_menu_study_004_study_info_tap(drv, runner):
    """TC-MENU-STUDY-004 | Study Information 탭 → 스터디 정보 화면 진입"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    open_menu(drv, wait=2.0)
    drv.tap_text("Study Information", timeout=5)
    time.sleep(1.5)
    visible = (
        drv.is_visible_text("Study ID", timeout=3)
        or drv.is_visible_text("Patient", timeout=2)
        or drv.is_visible_text("Study Duration", timeout=2)
    )
    drv.drv.press_keycode(4)  # 스터디 정보 → 메뉴
    time.sleep(0.5)
    drv.drv.press_keycode(4)  # 메뉴 → 메인
    time.sleep(0.5)
    runner.assert_true(visible, "Study Information screen not opened")


def test_menu_study_005_device_info_tap(drv, runner):
    """TC-MENU-STUDY-005 | Device Information 탭 → 기기 정보 화면 진입"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    open_menu(drv, wait=2.0)
    drv.tap_text("Device Information", timeout=5)
    time.sleep(1.5)
    visible = (
        drv.is_visible_text("Device", timeout=3)
        or drv.is_visible_text("Serial", timeout=2)
        or drv.is_visible_text("Firmware", timeout=2)
    )
    drv.drv.press_keycode(4)
    time.sleep(0.5)
    drv.drv.press_keycode(4)
    time.sleep(0.5)
    runner.assert_true(visible, "Device Information screen not opened")


TESTS = [
    test_menu_study_000_study_registered,
    test_menu_study_001_device_info_visible,
    test_menu_study_002_study_info_visible,
    test_menu_study_003_sections_visible,
    test_menu_study_004_study_info_tap,
    test_menu_study_005_device_info_tap,
]
