"""
TC-MAIN (iOS): Measurement main screen regression tests.
Mirrors main_screen.py but uses helpers_ios and ios_go_back instead of press_keycode(4).
"""
import time
import logging

from src.regression.helpers_ios import go_to_main, ios_go_back

log = logging.getLogger(__name__)

_MAIN_TEXT    = "My Study Progress"
_LOG_SYMPTOMS = "Log Symptoms"
_START_STUDY  = "Start Study"
_NO_STUDY     = "No study information"


def _not_started(drv) -> bool:
    return drv.is_visible_text(_START_STUDY, timeout=2, contains=False)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_main_000_study_started(drv, runner):
    """TC-MAIN-000 | Pre-check: study active (Log Symptoms visible)"""
    if drv.is_visible_text(_NO_STUDY, timeout=3):
        runner.fail("No study registered in web portal")
    if not drv.is_visible_text(_LOG_SYMPTOMS, timeout=15):
        runner.fail("Study not started — 'Log Symptoms' not visible within 15s")


def test_main_001_sections_visible(drv, runner):
    """TC-MAIN-001 | My Study Progress / Device Status / Real-time ECG tabs visible"""
    if _not_started(drv):
        return
    runner.assert_true(drv.is_visible_text(_MAIN_TEXT),        "My Study Progress not visible")
    runner.assert_true(drv.is_visible_text("Device Status"),    "Device Status tab not visible")
    runner.assert_true(drv.is_visible_text("Real-time ECG"),    "Real-time ECG tab not visible")


def test_main_002_status_cards_visible(drv, runner):
    """TC-MAIN-002 | Network / Bluetooth / Battery status cards visible"""
    if _not_started(drv):
        return
    runner.assert_true(drv.is_visible_text("Network"),   "Network card not visible")
    runner.assert_true(drv.is_visible_text("Bluetooth"), "Bluetooth card not visible")
    runner.assert_true(drv.is_visible_text("Battery"),   "Battery card not visible")


def test_main_003_log_symptoms_button(drv, runner):
    """TC-MAIN-003 | Log Symptoms button visible"""
    if _not_started(drv):
        return
    btn = drv.find(_LOG_SYMPTOMS, timeout=5)
    runner.assert_true(btn is not None, "Log Symptoms button not visible")


def test_main_004_realtime_ecg_tab(drv, runner):
    """TC-MAIN-004 | Real-time ECG tab → Live ECG Signal visible"""
    if _not_started(drv):
        return
    drv.tap_text("Real-time ECG", timeout=5)
    time.sleep(1.5)
    visible = drv.is_visible_text("Live ECG Signal", timeout=5)
    try:
        drv.tap_text("Device Status", timeout=3)
        time.sleep(0.5)
    except Exception:
        try:
            drv.tap_text("OK", timeout=2, contains=False)
        except Exception:
            pass
        try:
            go_to_main(drv)
        except Exception:
            pass
    runner.assert_true(visible, "Live ECG Signal not visible on Real-time ECG tab")


def test_main_005_study_progress_visible(drv, runner):
    """TC-MAIN-005 | Study progress info visible"""
    if _not_started(drv):
        return
    runner.assert_true(
        drv.is_visible_text(_MAIN_TEXT, timeout=3),
        "My Study Progress section not visible"
    )


def test_main_006_back_blocked(drv, runner):
    """TC-MAIN-006 | iOS back gesture → stays on main screen"""
    if _not_started(drv):
        return
    ios_go_back(drv)
    time.sleep(1.5)
    runner.assert_true(
        drv.is_visible_text(_LOG_SYMPTOMS, timeout=3),
        "Back gesture left main screen"
    )


TESTS = [
    test_main_000_study_started,
    test_main_001_sections_visible,
    test_main_002_status_cards_visible,
    test_main_003_log_symptoms_button,
    test_main_004_realtime_ecg_tab,
    test_main_005_study_progress_visible,
    test_main_006_back_blocked,
]
