"""
AK 앱 Log Symptoms 기반 증상 주입 워크플로우

흐름:
  1. 앱 포그라운드 확인
  2. 알려진 팝업 처리 (Cannot find your S-Patch / Reset your S-Patch)
  3. 메인 측정 화면(Log Symptoms 버튼) 확인
  4. Log Symptoms 탭
  5. 증상 선택 (없으면 랜덤) — Activity 없음
  6. Save 제출
  7. 메인 화면 복귀 확인

AK 앱 증상 목록:
  Chest pain / discomfort, Shortness of breath, Dizziness,
  Fainting, Palpitations / Heart pounding, Nausea
"""
import logging
import random
import time

from src.driver import AndroidDriver
from src.retry import retry
from src.workflows.popup_handler import handle_any_popup

log = logging.getLogger(__name__)

SYMPTOMS = [
    "Chest pain / discomfort",
    "Shortness of breath",
    "Dizziness",
    "Fainting",
    "Palpitations / Heart pounding",
    "Nausea",
]

_MAIN_SCREEN_TEXT  = "Log Symptoms"
_LOG_SYMPTOMS_BTN  = "Log Symptoms"
_SAVE_BTN          = "Save"
_DIARY_X_BTN       = (1009, 1226)   # X close button on Log Symptoms sheet (Pixel 7)


@retry(tries=3, delay=5)
def inject_symptom_event(
    d: AndroidDriver,
    symptoms: list[str] | None = None,
    activities: list[str] | None = None,  # AK has no activity section — ignored
):
    """Log Symptoms 시트에서 증상 주입 후 메인 화면으로 복귀."""
    t_start = time.monotonic()
    symptom = (symptoms[0] if symptoms else None) or random.choice(SYMPTOMS)

    d.reporter.log_event("inject_start", {"symptom": symptom})
    log.info("[inject] 증상=%s", symptom)

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

    # ── 4. Log Symptoms 탭 ───────────────────────────────────────────
    d.tap_text(_LOG_SYMPTOMS_BTN, timeout=5)
    d.wait_idle(1.0)

    # ── 5. 증상 선택 ────────────────────────────────────────────────
    d.tap_text(symptom, timeout=5)
    d.wait_idle(0.3)

    # ── 6. Save 제출 ─────────────────────────────────────────────────
    d.tap_text(_SAVE_BTN, timeout=5)
    d.wait_idle(1.5)

    # ── 7. 메인 화면 복귀 확인 ───────────────────────────────────────
    if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        try:
            d.drv.tap([_DIARY_X_BTN])
            d.wait_idle(1.0)
        except Exception:
            pass
        if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
            d.screenshot("inject_submit_failed")
            raise RuntimeError("Log Symptoms 제출 후 메인 화면 복귀 실패")

    elapsed = time.monotonic() - t_start
    d.screenshot("inject_after")
    d.reporter.log_event("inject_done", {
        "symptom": symptom,
        "elapsed_sec": round(elapsed, 1),
    })
    log.info("[inject] 완료 (%.1fs)", elapsed)
