"""
TC-DIARY: Add Diary 화면 Regression Tests
측정 중 메인 화면에서 Add Diary 탭 후 진입 화면 검증
"""
import time
import random
import logging

from src.regression.helpers import DIARY_X_BTN

log = logging.getLogger(__name__)

_NO_STUDY_TEXT = "No study information"

SYMPTOMS = [
    "Abnormal Heartbeat/Palpitations",
    "Chest Pain/Discomfort",
    "Shortness of Breath",
    "Lightheadedness",
    "Weakness",
    "Fainted",
]

ACTIVITIES = [
    "Physical Work",
    "Non-physical activities (paperwork, computer, TV)",
    "Resting",
    "Walking",
    "Exercising",
]


def _open_diary(drv):
    drv.tap_text("Add Diary", timeout=5)
    time.sleep(1)


def _close_diary(drv):
    drv.drv.tap([DIARY_X_BTN])
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_diary_000_study_registered(drv, runner):
    """TC-DIARY-000 | Pre-check: study registered"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=3):
        runner.fail("No study registered in web portal")


def test_diary_001_sections_visible(drv, runner):
    """TC-DIARY-001 | Symptom / Activity 섹션 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    _open_diary(drv)
    runner.assert_true(drv.is_visible_text("Symptom"), "Symptom section not visible")
    runner.assert_true(drv.is_visible_text("Activity"), "Activity section not visible")
    _close_diary(drv)


def test_diary_002_symptom_list_visible(drv, runner):
    """TC-DIARY-002 | 증상 목록 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    _open_diary(drv)
    for symptom in SYMPTOMS:
        runner.assert_true(
            drv.is_visible_text(symptom, timeout=3),
            f"Symptom not visible: {symptom}"
        )
    _close_diary(drv)


def test_diary_003_random_inject(drv, runner):
    """TC-DIARY-003 | 랜덤 Symptom + Activity 선택 후 Add Diary 제출 → 메인 복귀"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    _open_diary(drv)
    symptom = random.choice(SYMPTOMS)
    activity = random.choice(ACTIVITIES)
    log.info("  선택 증상: %s", symptom)
    log.info("  선택 활동: %s", activity)
    drv.tap_text(symptom, timeout=5)
    time.sleep(0.3)
    drv.tap_text(activity, timeout=5)
    time.sleep(0.3)
    drv.tap_text("Add Diary", timeout=5)
    time.sleep(1.5)
    runner.assert_true(
        drv.is_visible_text("Study Information", timeout=5),
        f"Main screen not restored after Add Diary submit ({symptom})"
    )


def test_diary_003b_activity_list_visible(drv, runner):
    """TC-DIARY-003b | Activity 목록 표시"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    _open_diary(drv)
    for activity in ACTIVITIES:
        runner.assert_true(
            drv.is_visible_text(activity, timeout=3),
            f"Activity not visible: {activity}"
        )
    _close_diary(drv)


def test_diary_004_submit_without_symptom(drv, runner):
    """TC-DIARY-004 | 증상 미선택 → Add Diary 제출 가능 여부 확인"""
    if drv.is_visible_text(_NO_STUDY_TEXT, timeout=2):
        return
    _open_diary(drv)
    btn = drv.find("Add Diary", timeout=5)
    runner.assert_true(btn is not None, "Add Diary button not visible")
    # 버튼 활성화 상태만 확인 (제출 여부는 앱 정책에 따름)
    enabled = btn.get_attribute("enabled") == "true"
    if enabled:
        drv.tap_text("Add Diary", timeout=5)
        time.sleep(1.5)
        runner.assert_true(
            drv.is_visible_text("Study Information", timeout=5),
            "Main screen not restored after submitting without symptom"
        )
    else:
        _close_diary(drv)
        # 비활성화는 정상 동작으로 간주


TESTS = [
    test_diary_000_study_registered,
    test_diary_001_sections_visible,
    test_diary_002_symptom_list_visible,
    test_diary_003b_activity_list_visible,
    test_diary_003_random_inject,
    test_diary_004_submit_without_symptom,
]
