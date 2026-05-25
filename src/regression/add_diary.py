"""
TC-DIARY: Log Symptoms sheet regression tests (AK)
Requires study active. Taps Log Symptoms from main screen and validates the sheet.
Note: AK Log Symptoms has Symptom section only (no Activity section).
"""
import time
import random
import logging

from src.regression.helpers import close_sheet, go_to_main

log = logging.getLogger(__name__)

_MAIN_BTN   = "Log Symptoms"
_START_STUDY = "Start Study"
_NO_STUDY    = "No study information"

SYMPTOMS = [
    "Chest pain / discomfort",
    "Shortness of breath",
    "Dizziness",
    "Fainting",
    "Palpitations / Heart pounding",
    "Nausea",
]


def _not_started(drv) -> bool:
    return drv.is_visible_text(_START_STUDY, timeout=2)


def _dismiss_patch_popup(drv):
    """Dismiss 950/963 popup if visible and recover to main screen."""
    if drv.is_visible_text("Cannot find your S-Patch", timeout=2) or \
       drv.is_visible_text("Reset your S-Patch", timeout=1):
        try:
            drv.tap_text("OK", timeout=3, contains=False)
        except Exception:
            pass
        try:
            go_to_main(drv)
        except Exception:
            pass
        return True
    return False


def _open_sheet(drv):
    _dismiss_patch_popup(drv)
    drv.tap_text(_MAIN_BTN, timeout=5)
    time.sleep(1)


def _close_sheet(drv):
    close_sheet(drv)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_diary_000_study_started(drv, runner):
    """TC-DIARY-000 | Pre-check: study active"""
    if drv.is_visible_text(_NO_STUDY, timeout=3):
        runner.fail("No study registered in web portal")
    if _not_started(drv):
        runner.fail("Study not started — 'Start Study' button still visible")


def test_diary_001_sheet_opens(drv, runner):
    """TC-DIARY-001 | Log Symptoms tap → sheet opens, Symptom section visible"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    runner.assert_true(drv.is_visible_text("Symptom"), "Symptom section not visible")
    _close_sheet(drv)


def test_diary_002_symptom_list_visible(drv, runner):
    """TC-DIARY-002 | All 6 symptoms listed"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    for symptom in SYMPTOMS:
        runner.assert_true(
            drv.is_visible_text(symptom, timeout=3),
            f"Symptom not visible: {symptom}"
        )
    _close_sheet(drv)


def test_diary_003_random_inject(drv, runner):
    """TC-DIARY-003 | Select random symptom → Save → returns to main screen"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    symptom = random.choice(SYMPTOMS)
    log.info("  Selected symptom: %s", symptom)
    drv.tap_text(symptom, timeout=5)
    time.sleep(0.3)
    drv.tap_text("Save", timeout=5)
    time.sleep(1.5)
    runner.assert_true(
        drv.is_visible_text(_MAIN_BTN, timeout=5),
        f"Main screen not restored after Save ({symptom})"
    )


def test_diary_004_close_x_button(drv, runner):
    """TC-DIARY-004 | X button → sheet closes, returns to main screen"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    runner.assert_true(drv.is_visible_text("Symptom", timeout=3), "Sheet not opened")
    _close_sheet(drv)
    runner.assert_true(
        drv.is_visible_text(_MAIN_BTN, timeout=5),
        "Main screen not restored after X button"
    )


def test_diary_005_save_without_symptom(drv, runner):
    """TC-DIARY-005 | No symptom selected → Save button state check"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    btn = drv.find("Save", timeout=5)
    runner.assert_true(btn is not None, "Save button not visible")
    enabled = btn.get_attribute("enabled") == "true"
    if enabled:
        log.warning("TC-DIARY-005: Save enabled without symptom (server-side validation)")
        drv.tap_text("Save", timeout=5)
        time.sleep(1.5)
        if drv.is_visible_text("Symptom", timeout=2):
            _close_sheet(drv)
    else:
        log.info("TC-DIARY-005: Save disabled without symptom (client-side validation)")
        _close_sheet(drv)


TESTS = [
    test_diary_000_study_started,
    test_diary_001_sheet_opens,
    test_diary_002_symptom_list_visible,
    test_diary_003_random_inject,
    test_diary_004_close_x_button,
    test_diary_005_save_without_symptom,
]
