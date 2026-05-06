"""
AK 앱 Add Diary 기반 증상/활동 주입 워크플로우

흐름:
  1. 앱 포그라운드 확인
  2. 알려진 팝업 처리 (Cannot find your S-Patch / Reset your S-Patch)
  3. 메인 측정 화면(Add Diary 버튼) 확인
  4. Add Diary 탭
  5. 증상 선택 (없으면 랜덤)
  6. 활동 선택 (없으면 랜덤)
  7. Add Diary 제출
  8. 메인 화면 복귀 확인

AK 앱 증상 목록:
  Abnormal Heartbeat/Palpitations, Chest Pain/Discomfort,
  Shortness of Breath, Lightheadedness, Weakness, Fainted

AK 앱 활동 목록:
  Physical Work, Non-physical activities (paperwork, computer, TV),
  Resting, Walking, Exercising
"""
import logging
import random
import time

from src.driver import AndroidDriver
from src.retry import retry
from src.workflows.popup_handler import handle_any_popup

log = logging.getLogger(__name__)

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

_MAIN_SCREEN_TEXT = "Study Information"
_ADD_DIARY_BTN    = "Add Diary"
# X 버튼 좌표 (Pixel 7 1080x2340 기준)
_DIARY_X_BTN      = (1004, 258)


@retry(tries=3, delay=5)
def inject_symptom_event(
    d: AndroidDriver,
    symptoms: list[str] | None = None,
    activities: list[str] | None = None,
):
    """
    Add Diary 화면에서 증상+활동 주입 후 메인 화면으로 복귀.

    symptoms, activities 미지정 시 각각 랜덤 1개 선택.
    """
    t_start  = time.monotonic()
    symptom  = (symptoms[0] if symptoms else None) or random.choice(SYMPTOMS)
    activity = (activities[0] if activities else None) or random.choice(ACTIVITIES)

    d.reporter.log_event("inject_start", {"symptom": symptom, "activity": activity})
    log.info("[inject] 증상=%s  활동=%s", symptom, activity)

    # ── 1. 앱 포그라운드 ──────────────────────────────────────────────
    d.bring_to_foreground()
    d.wait_idle(1.0)

    # ── 2. 알려진 팝업 처리 ──────────────────────────────────────────
    handle_any_popup(d)

    # ── 3. 메인 화면 확인 ────────────────────────────────────────────
    if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        d.screenshot("inject_not_on_main_screen")
        raise RuntimeError(f"메인 측정 화면이 아님 — '{_MAIN_SCREEN_TEXT}' 미표시")

    d.screenshot("inject_before")

    # ── 4. Add Diary 탭 ──────────────────────────────────────────────
    d.tap_text(_ADD_DIARY_BTN, timeout=5)
    d.wait_idle(1.0)

    # ── 5. 증상 선택 ────────────────────────────────────────────────
    d.tap_text(symptom, timeout=5)
    d.wait_idle(0.3)

    # ── 6. 활동 선택 ────────────────────────────────────────────────
    d.tap_text(activity, timeout=5)
    d.wait_idle(0.3)

    # ── 7. 제출 ──────────────────────────────────────────────────────
    d.tap_text(_ADD_DIARY_BTN, timeout=5)
    d.wait_idle(1.5)

    # ── 8. 메인 화면 복귀 확인 ───────────────────────────────────────
    if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        # Add Diary 화면이 아직 열려있으면 X로 닫고 재확인
        try:
            d.drv.tap([_DIARY_X_BTN])
            d.wait_idle(1.0)
        except Exception:
            pass
        if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
            d.screenshot("inject_submit_failed")
            raise RuntimeError("Add Diary 제출 후 메인 화면 복귀 실패")

    elapsed = time.monotonic() - t_start
    d.screenshot("inject_after")
    d.reporter.log_event("inject_done", {
        "symptom": symptom,
        "activity": activity,
        "elapsed_sec": round(elapsed, 1),
    })
    log.info("[inject] 완료 (%.1fs)", elapsed)
