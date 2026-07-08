"""
AK app popup handler

Targets:
  - Cannot find your S-Patch (code 950) : tap Ok → reconnection required
  - Reset your S-Patch      (code 963) : tap Ok → device reset required

Call handle_any_popup() before each injection to automatically handle known popups.
"""
import logging
import time

from src.driver import AndroidDriver

log = logging.getLogger(__name__)

_CANNOT_FIND_PATCH = "Cannot find your S-Patch"
_RESET_PATCH       = "Reset your S-Patch"
_OK_BTN            = "Ok"


def handle_cannot_find_patch(d: AndroidDriver) -> bool:
    """Handle S-Patch not found popup (code 950). Returns False if popup is not present."""
    if not d.is_visible_text(_CANNOT_FIND_PATCH, timeout=2):
        return False

    log.warning("[popup] 'Cannot find your S-Patch' (950) popup detected")
    d.reporter.log_event("popup_cannot_find_patch", {})

    try:
        d.tap_text(_OK_BTN, timeout=5, contains=False)
        d.wait_idle(1.5)
    except Exception as e:
        log.warning("[popup] Failed to tap Ok button: %s", e)

    return True


def handle_reset_patch(d: AndroidDriver) -> bool:
    """Handle S-Patch reset required popup (code 963). Returns False if popup is not present."""
    if not d.is_visible_text(_RESET_PATCH, timeout=2):
        return False

    log.warning("[popup] 'Reset your S-Patch' (963) popup detected")
    d.reporter.log_event("popup_reset_patch", {})

    try:
        d.tap_text(_OK_BTN, timeout=5, contains=False)
        d.wait_idle(1.5)
    except Exception as e:
        log.warning("[popup] Failed to tap Ok button: %s", e)

    return True


# Unexpected in-app error popups (e.g. "Test failed - No time zone found with
# key America/Chicago"). These are app-internal modals, so the system-popup
# detector (dismiss_unexpected_popups) never sees them — without this handler
# they block the main screen and stall the long run.
_GENERIC_ERROR_MARKERS = [
    "Test failed",
    "No time zone",
    "Something went wrong",
    "오류가 발생",
]
_GENERIC_DISMISS_BTNS = ["Ok", "OK", "Confirm", "확인", "Close", "Retry"]


def handle_generic_error_popup(d: AndroidDriver) -> bool:
    """Dismiss unexpected in-app error popups so the long run keeps going."""
    marker = None
    for m in _GENERIC_ERROR_MARKERS:
        if d.is_visible_text(m, timeout=1):
            marker = m
            break
    if marker is None:
        return False

    log.warning("[popup] unexpected in-app error popup detected (marker=%r)", marker)
    d.reporter.log_event("popup_generic_error", {"marker": marker})
    try:
        d.screenshot("popup_generic_error")
    except Exception:
        pass

    for btn in _GENERIC_DISMISS_BTNS:
        try:
            d.tap_text(btn, timeout=2, contains=False)
            d.wait_idle(1.0)
            log.info("[popup] error popup dismissed via '%s'", btn)
            return True
        except Exception:
            pass

    # Last resort: back key (Android); harmless no-op on iOS drivers
    try:
        d.drv.press_keycode(4)
        d.wait_idle(1.0)
    except Exception:
        pass
    return True


def handle_any_popup(d: AndroidDriver) -> bool:
    """Detect and handle known popups in order. Returns True if at least one was handled."""
    handled = False
    if handle_cannot_find_patch(d):
        handled = True
    if handle_reset_patch(d):
        handled = True
    if handle_generic_error_popup(d):
        handled = True
    return handled
