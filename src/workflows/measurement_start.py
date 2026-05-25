"""
AK app main measurement screen check (ensure_on_main_screen)

Since the AK app requires study start to be done manually, at automation start
we only verify that the main measurement screen (Study Information + Add Diary) is shown.

Paths:
  A) Already on main screen → return immediately
  B) Popup (Cannot find your S-Patch / Reset your S-Patch) → handle then re-check
  C) Not on main screen → RuntimeError (study start required)
"""
import logging
import time

from src.driver import AndroidDriver
from src.retry import retry
from src.workflows.popup_handler import handle_any_popup

log = logging.getLogger(__name__)

_MAIN_SCREEN_TEXT = "Log Symptoms"   # AK main screen identifier
_LOG_SYMPTOMS_BTN = "Log Symptoms"


@retry(tries=3, delay=5)
def ensure_on_main_screen(d: AndroidDriver):
    """Verify the app is on the main measurement screen. Raises RuntimeError if not."""
    d.reporter.log_event("ensure_on_main_screen", {})

    # ── Bring app to foreground ──────────────────────────────────────────────
    d.bring_to_foreground()
    d.wait_idle(2.0)

    # ── Close Log Symptoms sheet if open ─────────────────────
    if d.is_visible_text("Symptom", timeout=1):
        log.info("[setup] Log Symptoms sheet open detected → closing with Back key")
        try:
            d.drv.press_keycode(4)  # Back key — device-independent
            d.wait_idle(1.0)
        except Exception:
            pass

    # ── Handle popups ──────────────────────────────────────────────────
    handle_any_popup(d)

    # ── Confirm main screen ────────────────────────────────────────────
    if d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        d.reporter.log_event("main_screen_confirmed", {})
        log.info("[setup] Main measurement screen confirmed")
        return

    # If Start Study button is visible, study has not been started yet
    if d.is_visible_text("Start Study", timeout=2):
        d.screenshot("ensure_main_screen_failed")
        raise RuntimeError("Start Study screen detected — please run Start Study in the app first.")

    # Wait once more and re-check (app may still be loading)
    time.sleep(3)
    handle_any_popup(d)

    if d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        d.reporter.log_event("main_screen_confirmed", {})
        return

    d.screenshot("ensure_main_screen_failed")
    raise RuntimeError(
        f"Not on main measurement screen — '{_MAIN_SCREEN_TEXT}' not displayed. "
        "Please run Start Study in the app first."
    )
