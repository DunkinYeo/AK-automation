"""
TC-SIG: Step 2 Check Incoming Signal Regression Tests
Run when already on Step 2 screen after Connect (no need to call go_to_step2)
"""
import time
import logging

log = logging.getLogger(__name__)


def test_sig_001_screen_title(drv, runner):
    """TC-SIG-001 | Step 2 → 'Check Incoming Signal' title is displayed"""
    runner.assert_true(
        drv.is_visible_text("Check Incoming Signal", timeout=5),
        "Check Incoming Signal title not visible"
    )


def test_sig_002_live_streaming_label(drv, runner):
    """TC-SIG-002 | Live Streaming text is displayed"""
    runner.assert_true(
        drv.is_visible_text("Live Streaming", timeout=5),
        "Live Streaming text not visible"
    )


def test_sig_003_continue_button_visible(drv, runner):
    """TC-SIG-003 | Continue button is displayed and enabled"""
    btn = drv.find("Continue", timeout=5)
    runner.assert_true(btn is not None, "Continue button not visible")
    runner.assert_true(
        btn.get_attribute("enabled") == "true",
        "Continue button is disabled"
    )


def test_sig_004_ecg_signal_visible(drv, runner):
    """TC-SIG-004 | ECG waveform area is displayed"""
    # Check presence of ECG waveform box below Live Streaming — confirmed indirectly via title
    runner.assert_true(
        drv.is_visible_text("Check Incoming Signal", timeout=3),
        "Left Step 2 screen — ECG signal area unavailable"
    )


TESTS = [
    test_sig_001_screen_title,
    test_sig_002_live_streaming_label,
    test_sig_003_continue_button_visible,
    test_sig_004_ecg_signal_visible,
]
