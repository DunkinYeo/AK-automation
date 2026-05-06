"""
AK 앱 메인 측정 화면 확인 (ensure_on_main_screen)

AK 앱은 검사 시작이 수동이므로, 자동화 시작 시점에
이미 메인 측정 화면(Study Information + Add Diary)에 있는지만 확인.

경로:
  A) 이미 메인 화면 → 즉시 반환
  B) 팝업(Cannot find your S-Patch / Reset your S-Patch) → 처리 후 재확인
  C) 메인 화면 아님 → RuntimeError (검사 시작 필요)
"""
import logging
import time

from src.driver import AndroidDriver
from src.retry import retry
from src.workflows.popup_handler import handle_any_popup

log = logging.getLogger(__name__)

_MAIN_SCREEN_TEXT = "Log Symptoms"   # AK 메인 화면 식별자
_LOG_SYMPTOMS_BTN = "Log Symptoms"
_DIARY_X_BTN      = (1009, 1226)   # Log Symptoms 시트 X 버튼 (Pixel 7 기준)


@retry(tries=3, delay=5)
def ensure_on_main_screen(d: AndroidDriver):
    """앱이 메인 측정 화면에 있는지 확인. 아니면 RuntimeError."""
    d.reporter.log_event("ensure_on_main_screen", {})

    # ── 앱 포그라운드 ──────────────────────────────────────────────
    d.bring_to_foreground()
    d.wait_idle(2.0)

    # ── Log Symptoms 시트가 열려 있으면 닫기 ─────────────────────
    if d.is_visible_text("Symptom", timeout=1):
        log.info("[setup] Log Symptoms 시트 열림 감지 → X 버튼으로 닫기")
        try:
            d.drv.tap([_DIARY_X_BTN])
            d.wait_idle(1.0)
        except Exception:
            pass

    # ── 팝업 처리 ──────────────────────────────────────────────────
    handle_any_popup(d)

    # ── 메인 화면 확인 ────────────────────────────────────────────
    if d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        d.reporter.log_event("main_screen_confirmed", {})
        log.info("[setup] 메인 측정 화면 확인됨")
        return

    # Start Study 버튼이 보이면 스터디가 시작되지 않은 상태
    if d.is_visible_text("Start Study", timeout=2):
        d.screenshot("ensure_main_screen_failed")
        raise RuntimeError("Start Study 화면 감지 — 앱에서 Start Study를 먼저 실행해주세요.")

    # 한 번 더 대기 후 재확인 (앱 로딩 중일 수 있음)
    time.sleep(3)
    handle_any_popup(d)

    if d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        d.reporter.log_event("main_screen_confirmed", {})
        return

    d.screenshot("ensure_main_screen_failed")
    raise RuntimeError(
        f"메인 측정 화면이 아님 — '{_MAIN_SCREEN_TEXT}' 미표시. "
        "앱에서 Start Study를 먼저 실행해주세요."
    )
