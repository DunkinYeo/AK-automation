"""
TC-DIARY: Log Symptoms 시트 Regression Tests (AK)
측정 중 메인 화면에서 Log Symptoms 탭 후 시트 검증
"""
import time
import random
import logging

from src.regression.helpers import DIARY_X_BTN

log = logging.getLogger(__name__)

_MAIN_BTN   = "Log Symptoms"
_START_STUDY = "Start Study"

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


def _open_sheet(drv):
    drv.tap_text(_MAIN_BTN, timeout=5)
    time.sleep(1)


def _close_sheet(drv):
    drv.drv.tap([DIARY_X_BTN])
    time.sleep(0.8)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_diary_000_study_started(drv, runner):
    """TC-DIARY-000 | Pre-check: 스터디 시작 여부 확인"""
    if _not_started(drv):
        runner.fail("Study not started — 'Start Study' button still visible")


def test_diary_001_sheet_opens(drv, runner):
    """TC-DIARY-001 | Log Symptoms 탭 → 시트 열림 및 Symptom 섹션 표시"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    runner.assert_true(drv.is_visible_text("Symptom"), "Symptom section not visible")
    _close_sheet(drv)


def test_diary_002_symptom_list_visible(drv, runner):
    """TC-DIARY-002 | 증상 목록 전체 표시"""
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
    """TC-DIARY-003 | 랜덤 증상 선택 → Save 제출 → 메인 화면 복귀"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    symptom = random.choice(SYMPTOMS)
    log.info("  선택 증상: %s", symptom)
    drv.tap_text(symptom, timeout=5)
    time.sleep(0.3)
    drv.tap_text("Save", timeout=5)
    time.sleep(1.5)
    runner.assert_true(
        drv.is_visible_text(_MAIN_BTN, timeout=5),
        f"Main screen not restored after Save ({symptom})"
    )


def test_diary_004_close_x_button(drv, runner):
    """TC-DIARY-004 | X 버튼 탭 → 시트 닫힘, 메인 화면 복귀"""
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
    """TC-DIARY-005 | 증상 미선택 → Save 버튼 활성화/비활성화 상태 확인"""
    if _not_started(drv):
        return
    _open_sheet(drv)
    btn = drv.find("Save", timeout=5)
    runner.assert_true(btn is not None, "Save button not visible")
    enabled = btn.get_attribute("enabled") == "true"
    if enabled:
        log.warning("TC-DIARY-005: Save enabled without symptom selection (server validates)")
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
