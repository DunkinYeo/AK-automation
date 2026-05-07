"""
TC-MENU: Step 1 Hamburger Menu Regression Tests
Menu cases that can be verified before serial input (without device connection)
"""
import time
import logging

from src.regression.helpers import open_menu, close_menu

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_menu_001_open(drv, runner):
    """TC-MENU-001 | Tap ≡ → enter menu screen"""
    open_menu(drv, wait=2.0)
    runner.assert_true(
        drv.is_visible_text("Setting"),
        "Setting section not visible after opening menu"
    )
    close_menu(drv)


def test_menu_002_sections_visible(drv, runner):
    """TC-MENU-002 | Menu section items displayed correctly (Setting / Terms and Information / Guide)"""
    open_menu(drv, wait=2.0)
    runner.assert_true(drv.is_visible_text("Setting"), "Setting not visible")
    runner.assert_true(drv.is_visible_text("Terms and Information"), "Terms and Information not visible")
    runner.assert_true(drv.is_visible_text("Guide"), "Guide not visible")
    close_menu(drv)


def test_menu_003_live_streaming_duration_default(drv, runner):
    """TC-MENU-003 | Live Streaming Duration default value 15s is displayed"""
    open_menu(drv, wait=2.0)
    runner.assert_true(
        drv.is_visible_text("Live Streaming Duration"),
        "Live Streaming Duration not visible"
    )
    runner.assert_true(
        drv.is_visible_text("15s"),
        "Default duration '15s' not visible"
    )
    close_menu(drv)


def test_menu_004_version_information_visible(drv, runner):
    """TC-MENU-004 | Version Information item is displayed"""
    open_menu(drv, wait=2.0)
    runner.assert_true(
        drv.is_visible_text("Version Information"),
        "Version Information not visible"
    )
    close_menu(drv)


def test_menu_005_device_study_info_hidden(drv, runner):
    """TC-MENU-005 | Disconnected state → Device/Study Information not displayed"""
    open_menu(drv, wait=2.0)
    runner.assert_false(
        drv.is_visible_text("Device Information", timeout=2),
        "Device Information should not appear when disconnected"
    )
    runner.assert_false(
        drv.is_visible_text("Study Information", timeout=2),
        "Study Information should not appear when disconnected"
    )
    close_menu(drv)


def test_menu_006_patch_placement_visible(drv, runner):
    """TC-MENU-006 | Patch Placement item is displayed"""
    open_menu(drv, wait=2.0)
    runner.assert_true(
        drv.is_visible_text("Patch Placement"),
        "Patch Placement not visible"
    )
    close_menu(drv)


def test_menu_007_version_information_tap(drv, runner):
    """TC-MENU-007 | Tap Version Information → version info screen is displayed"""
    open_menu(drv, wait=2.0)
    drv.tap_text("Version Information", timeout=5)
    time.sleep(1.0)
    # Check whether the version string or app name is shown on the version info screen
    visible = drv.is_visible_text("Version", timeout=3)
    drv.drv.press_keycode(4)  # Version Info → menu
    time.sleep(0.5)
    drv.drv.press_keycode(4)  # menu → Step 1
    time.sleep(0.5)
    runner.assert_true(visible, "Version Information screen not opened")


def test_menu_008_patch_placement_tap(drv, runner):
    """TC-MENU-008 | Tap Patch Placement → placement guide screen is displayed"""
    open_menu(drv, wait=2.0)
    drv.tap_text("Patch Placement", timeout=5)
    time.sleep(2.0)
    # Guide screen: placement-related text such as "Patch Placement" or "Power Button Side"
    visible = (
        drv.is_visible_text("Patch Placement", timeout=3)
        or drv.is_visible_text("Power Button", timeout=2)
        or drv.is_visible_text("Battery Side", timeout=2)
    )
    drv.drv.press_keycode(4)
    time.sleep(0.5)
    runner.assert_true(visible, "Patch Placement screen not opened")


def test_menu_009_back_returns_to_step1(drv, runner):
    """TC-MENU-009 | Back button from menu → returns to Step 1 screen"""
    open_menu(drv, wait=2.0)
    close_menu(drv)
    runner.assert_true(
        drv.is_visible_text("Connect Your S-Patch"),
        "Step 1 screen not restored after closing menu"
    )


TESTS = [
    test_menu_001_open,
    test_menu_002_sections_visible,
    test_menu_003_live_streaming_duration_default,
    test_menu_004_version_information_visible,
    test_menu_005_device_study_info_hidden,
    test_menu_006_patch_placement_visible,
    test_menu_007_version_information_tap,
    test_menu_008_patch_placement_tap,
    test_menu_009_back_returns_to_step1,
]
