"""
TC-STUDY: No Study Information Popup Regression Tests
Verify the popup that appears after tapping Continue when no study is registered on the web
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
    raise Exception("No Study Information popup not displayed (waited 10s)")


def _dismiss_popup(drv):
    if drv.is_visible_text("Confirm", timeout=3):
        drv.tap_text("Confirm", timeout=5)
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_study_001_popup_content(drv, runner):
    """TC-STUDY-001~003 | Popup displayed + error code (40103) + guide message confirmed"""
    _trigger_no_study_popup(drv)
    runner.assert_true(
        drv.is_visible_text("No Study Information"),
        "No Study Information popup should be displayed"
    )
    runner.assert_true(
        drv.is_visible_text("40103"),
        "Error code '40103' should be displayed in the popup"
    )
    runner.assert_true(
        drv.is_visible_text("There is no study information"),
        "Popup guide message not displayed"
    )
    _dismiss_popup(drv)


def test_study_004_confirm_closes_popup(drv, runner):
    """TC-STUDY-004 | Tap Confirm → popup closes, Step 2 remains"""
    _trigger_no_study_popup(drv)
    drv.tap_text("Confirm", timeout=5)
    time.sleep(1)
    runner.assert_false(
        drv.is_visible_text("No Study Information", timeout=2),
        "Popup should close after tapping Confirm"
    )
    runner.assert_true(
        drv.is_visible_text("Check Incoming Signal", timeout=3),
        "Step 2 screen should remain after tapping Confirm"
    )


def test_study_005_x_button_closes_popup(drv, runner):
    """TC-STUDY-005 | Tap X button → popup closes"""
    _trigger_no_study_popup(drv)
    drv.drv.tap([STUDY_POPUP_X_BTN])
    time.sleep(1)
    runner.assert_false(
        drv.is_visible_text("No Study Information", timeout=2),
        "Popup should close after tapping X button"
    )


TESTS = [
    test_study_001_popup_content,
    test_study_004_confirm_closes_popup,
    test_study_005_x_button_closes_popup,
]
