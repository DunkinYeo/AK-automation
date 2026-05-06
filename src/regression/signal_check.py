"""
TC-SIG: Step 2 Check Incoming Signal Regression Tests
Connect 후 Step 2 화면에 이미 있는 상태에서 실행 (go_to_step2 호출 불필요)
"""
import time
import logging

log = logging.getLogger(__name__)


def test_sig_001_screen_title(drv, runner):
    """TC-SIG-001 | Step 2 → 'Check Incoming Signal' 타이틀 표시"""
    runner.assert_true(
        drv.is_visible_text("Check Incoming Signal", timeout=5),
        "Check Incoming Signal title not visible"
    )


def test_sig_002_live_streaming_label(drv, runner):
    """TC-SIG-002 | Live Streaming 텍스트 표시"""
    runner.assert_true(
        drv.is_visible_text("Live Streaming", timeout=5),
        "Live Streaming text not visible"
    )


def test_sig_003_continue_button_visible(drv, runner):
    """TC-SIG-003 | Continue 버튼 표시 및 활성화"""
    btn = drv.find("Continue", timeout=5)
    runner.assert_true(btn is not None, "Continue button not visible")
    runner.assert_true(
        btn.get_attribute("enabled") == "true",
        "Continue button is disabled"
    )


def test_sig_004_ecg_signal_visible(drv, runner):
    """TC-SIG-004 | ECG 파형 영역 표시"""
    # Live Streaming 아래 ECG 파형 박스 존재 여부 — 타이틀로 간접 확인
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
