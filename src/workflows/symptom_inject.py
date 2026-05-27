"""
AK app Log Symptoms-based symptom injection workflow

Flow:
  1. Bring app to foreground
  2. Handle known popups (Cannot find your S-Patch / Reset your S-Patch)
  3. Confirm main measurement screen (Log Symptoms button)
  4. Tap Log Symptoms
  5. Select symptom (random if none provided) — no Activity section
  6. Submit via Save
  7. Confirm return to main screen

AK app symptom list:
  Chest pain / discomfort, Shortness of breath, Dizziness,
  Fainting, Palpitations / Heart pounding, Nausea
"""
import logging
import random
import time

from src.driver import AndroidDriver
from src.retry import retry
from src.workflows.popup_handler import handle_any_popup
from src.regression.helpers import go_to_main

log = logging.getLogger(__name__)

SYMPTOMS = [
    "Chest pain / discomfort",
    "Shortness of breath",
    "Dizziness",
    "Fainting",
    "Palpitations / Heart pounding",
    "Nausea",
]

ACTIVITIES: list[str] = []  # AK has no activity section

_MAIN_SCREEN_TEXT  = "Log Symptoms"
_LOG_SYMPTOMS_BTN  = "Log Symptoms"
_SAVE_BTN          = "Save"


@retry(tries=3, delay=5)
def inject_symptom_event(
    d: AndroidDriver,
    symptoms: list[str] | None = None,
    activities: list[str] | None = None,  # AK has no activity section — ignored
):
    """Inject a symptom via the Log Symptoms sheet, then return to the main screen."""
    t_start = time.monotonic()
    symptom = (symptoms[0] if symptoms else None) or random.choice(SYMPTOMS)

    d.reporter.log_event("inject_start", {"symptom": symptom})
    log.info("[inject] symptom=%s", symptom)

    # ── 1. Bring app to foreground ──────────────────────────────────────────────
    d.bring_to_foreground()
    d.wait_idle(1.5)

    # ── 2. Handle known popups ──────────────────────────────────────────
    handle_any_popup(d)

    # ── 3. Confirm main screen — navigate there if not already on it ──────────
    if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        log.info("[inject] Not on main screen — navigating via go_to_main()")
        d.screenshot("inject_not_on_main_before_nav")
        go_to_main(d)
    if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        d.screenshot("inject_not_on_main_screen")
        raise RuntimeError(f"Not on main measurement screen — '{_MAIN_SCREEN_TEXT}' not displayed")

    d.screenshot("inject_before")

    # ── 4. Tap Log Symptoms ───────────────────────────────────────────
    d.tap_text(_LOG_SYMPTOMS_BTN, timeout=5)
    d.wait_idle(1.0)

    # ── 5. Select symptom ────────────────────────────────────────────────
    d.tap_text(symptom, timeout=5)
    d.wait_idle(0.3)

    # ── 6. Submit via Save ─────────────────────────────────────────────────
    d.tap_text(_SAVE_BTN, timeout=5)
    d.wait_idle(1.5)

    # ── 7. Confirm return to main screen ───────────────────────────────────────────
    if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
        try:
            d.drv.press_keycode(4)  # Back key — close sheet on any device
            d.wait_idle(1.0)
        except Exception:
            pass
        if not d.is_visible_text(_MAIN_SCREEN_TEXT, timeout=5):
            d.screenshot("inject_submit_failed")
            raise RuntimeError("Failed to return to main screen after Log Symptoms submission")

    elapsed = time.monotonic() - t_start
    d.screenshot("inject_after")
    d.reporter.log_event("inject_done", {
        "symptom": symptom,
        "elapsed_sec": round(elapsed, 1),
    })
    log.info("[inject] Complete (%.1fs)", elapsed)
