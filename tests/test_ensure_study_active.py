"""
Regression tests for _ensure_study_active() (src/main.py): a final
precondition check right before the long-run scheduler starts.

Raised 2026-08-12: a real run started with the study never actually
registered/started on the device (app stuck on "Connect Your S-Patch").
Regression suites correctly reported "Study not started" as ordinary TC
failures, but nothing stopped the scheduler from starting anyway -- it
went on to schedule 40+ hourly jobs that all failed identically
("Session recovery failed") over ~43 hours before anyone noticed.

Run: .venv/bin/pytest tests/test_ensure_study_active.py -v
"""
import pytest

import src.main as main_mod

_SEL = {"symptom_add_text": "Log Symptoms"}


class _FakeDriver:
    def __init__(self, visible_texts: set[str]):
        self._visible = visible_texts

    def is_visible_text(self, text, timeout=2, contains=True):
        return text in self._visible


def test_passes_when_main_screen_indicator_visible():
    drv = _FakeDriver({"Log Symptoms"})
    main_mod._ensure_study_active(drv, _SEL)  # must not raise


def test_raises_when_stuck_on_connect_your_s_patch():
    """The exact real-world failure: neither the main indicator nor
    Start Study is visible (still on Step 1)."""
    drv = _FakeDriver(set())
    with pytest.raises(RuntimeError, match="not appear to be started"):
        main_mod._ensure_study_active(drv, _SEL)


def test_raises_when_stuck_on_start_study_screen():
    """Onboarding got as far as Start Study but it was never tapped --
    indicator not visible AND Start Study still is."""
    drv = _FakeDriver({"Start Study", "My Study Progress", "Device Status"})
    with pytest.raises(RuntimeError, match="not appear to be started"):
        main_mod._ensure_study_active(drv, _SEL)


def test_uses_custom_indicator_from_selectors():
    sel = {"symptom_add_text": "Add Diary"}
    drv = _FakeDriver({"Add Diary"})
    main_mod._ensure_study_active(drv, sel)  # must not raise

    drv2 = _FakeDriver({"Log Symptoms"})  # wrong indicator for this config
    with pytest.raises(RuntimeError):
        main_mod._ensure_study_active(drv2, sel)
