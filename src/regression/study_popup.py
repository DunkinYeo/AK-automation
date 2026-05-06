"""
TC-STUDY: No Study Information 팝업 Regression Tests
웹에 스터디 미등록 상태에서 Continue 탭 후 나타나는 팝업 검증
"""
import time
import logging

from src.regression.helpers import go_to_step2, STUDY_POPUP_X_BTN

log = logging.getLogger(__name__)


def _trigger_no_study_popup(drv):
    go_to_step2(drv)
    drv.tap_text("Continue", timeout=5, contains=False)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if drv.is_visible_text("No Study Information", timeout=2):
            return
        time.sleep(1)
    raise Exception("No Study Information 팝업 미표시 (10s 대기)")


def _dismiss_popup(drv):
    if drv.is_visible_text("Confirm", timeout=3):
        drv.tap_text("Confirm", timeout=5)
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_study_001_popup_content(drv, runner):
    """TC-STUDY-001~003 | 팝업 표시 + 에러 코드(40103) + 안내 문구 확인"""
    _trigger_no_study_popup(drv)
    runner.assert_true(
        drv.is_visible_text("No Study Information"),
        "No Study Information 팝업이 표시되어야 함"
    )
    runner.assert_true(
        drv.is_visible_text("40103"),
        "에러 코드 '40103'이 팝업에 표시되어야 함"
    )
    runner.assert_true(
        drv.is_visible_text("There is no study information"),
        "팝업 안내 문구 미표시"
    )
    _dismiss_popup(drv)


def test_study_004_confirm_closes_popup(drv, runner):
    """TC-STUDY-004 | Confirm 탭 → 팝업 닫힘, Step 2 유지"""
    _trigger_no_study_popup(drv)
    drv.tap_text("Confirm", timeout=5)
    time.sleep(1)
    runner.assert_false(
        drv.is_visible_text("No Study Information", timeout=2),
        "Confirm 탭 후 팝업이 닫혀야 함"
    )
    runner.assert_true(
        drv.is_visible_text("Check Incoming Signal", timeout=3),
        "Confirm 탭 후 Step 2 화면이 유지되어야 함"
    )


def test_study_005_x_button_closes_popup(drv, runner):
    """TC-STUDY-005 | X 버튼 탭 → 팝업 닫힘"""
    _trigger_no_study_popup(drv)
    drv.drv.tap([STUDY_POPUP_X_BTN])
    time.sleep(1)
    runner.assert_false(
        drv.is_visible_text("No Study Information", timeout=2),
        "X 버튼 탭 후 팝업이 닫혀야 함"
    )


TESTS = [
    test_study_001_popup_content,
    test_study_004_confirm_closes_popup,
    test_study_005_x_button_closes_popup,
]
