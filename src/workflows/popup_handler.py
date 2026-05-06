"""
AK 앱 팝업 핸들러

처리 대상:
  - Cannot find your S-Patch (코드 950) : Ok 탭 → 연결 재시도 필요
  - Reset your S-Patch      (코드 963) : Ok 탭 → 기기 초기화 필요

handle_any_popup() 을 매 주입 전에 호출하면 알려진 팝업을 자동 처리.
"""
import logging
import time

from src.driver import AndroidDriver

log = logging.getLogger(__name__)

_CANNOT_FIND_PATCH = "Cannot find your S-Patch"
_RESET_PATCH       = "Reset your S-Patch"
_OK_BTN            = "Ok"


def handle_cannot_find_patch(d: AndroidDriver) -> bool:
    """S-Patch 미발견 팝업(코드 950) 처리. 팝업이 없으면 False 반환."""
    if not d.is_visible_text(_CANNOT_FIND_PATCH, timeout=2):
        return False

    log.warning("[popup] 'Cannot find your S-Patch' (950) 팝업 감지")
    d.reporter.log_event("popup_cannot_find_patch", {})

    try:
        d.tap_text(_OK_BTN, timeout=5, contains=False)
        d.wait_idle(1.5)
    except Exception as e:
        log.warning("[popup] Ok 버튼 탭 실패: %s", e)

    return True


def handle_reset_patch(d: AndroidDriver) -> bool:
    """S-Patch 초기화 필요 팝업(코드 963) 처리. 팝업이 없으면 False 반환."""
    if not d.is_visible_text(_RESET_PATCH, timeout=2):
        return False

    log.warning("[popup] 'Reset your S-Patch' (963) 팝업 감지")
    d.reporter.log_event("popup_reset_patch", {})

    try:
        d.tap_text(_OK_BTN, timeout=5, contains=False)
        d.wait_idle(1.5)
    except Exception as e:
        log.warning("[popup] Ok 버튼 탭 실패: %s", e)

    return True


def handle_any_popup(d: AndroidDriver) -> bool:
    """알려진 팝업을 순서대로 감지·처리. 하나라도 처리했으면 True."""
    handled = False
    if handle_cannot_find_patch(d):
        handled = True
    if handle_reset_patch(d):
        handled = True
    return handled
