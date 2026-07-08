"""
TC-MENU (iOS): Step 1 Hamburger Menu Regression Tests
Mirrors menu_step1.py but uses helpers_ios for open_menu / close_menu / reset_to_step1.
"""
import time
import logging

from src.regression.helpers_ios import open_menu, close_menu, reset_to_step1, _ratio_tap

log = logging.getLogger(__name__)

# Menu item row positions (ratio of screen height, measured from screenshot on 375x812).
# Flat RN tree: menu rows are not tappable elements — coordinate taps required.
_MENU_ITEM_Y = {
    "Live Streaming Duration": 0.239,
    "Version Information":     0.373,
    "Patch Placement":         0.497,
}


def _tap_menu_item(drv, name: str):
    """Tap a menu row by measured coordinate (flat tree — no elements exposed)."""
    _ratio_tap(drv, 0.50, _MENU_ITEM_Y[name], f"menu item: {name}")
    time.sleep(1.0)


def _ios_go_back(drv):
    """
    Navigate back on iOS. Sub-screens (Version Information, Patch Placement)
    have a back-arrow at top-left; it is NOT an element in the flat RN tree,
    so tap it by coordinate (verified: ~9.8% x, ~10.5% y on 375x812).
    """
    _ratio_tap(drv, 0.098, 0.105, "back arrow (top-left)")
    time.sleep(1.0)


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
    """TC-MENU-002 | Menu sections displayed (Setting / Terms and Information / Guide)"""
    open_menu(drv, wait=2.0)
    runner.assert_true(drv.is_visible_text("Setting"), "Setting not visible")
    runner.assert_true(drv.is_visible_text("Terms and Information"), "Terms and Information not visible")
    runner.assert_true(drv.is_visible_text("Guide"), "Guide not visible")
    close_menu(drv)


def test_menu_003_live_streaming_duration_default(drv, runner):
    """TC-MENU-003 | Live Streaming Duration default 15s displayed"""
    open_menu(drv, wait=2.0)
    runner.assert_true(drv.is_visible_text("Live Streaming Duration"), "Live Streaming Duration not visible")
    runner.assert_true(drv.is_visible_text("15s"), "Default duration '15s' not visible")
    close_menu(drv)


def test_menu_004_version_information_visible(drv, runner):
    """TC-MENU-004 | Version Information item displayed"""
    open_menu(drv, wait=2.0)
    runner.assert_true(drv.is_visible_text("Version Information"), "Version Information not visible")
    close_menu(drv)


def test_menu_005_device_study_info_hidden(drv, runner):
    """TC-MENU-005 | Disconnected → Device/Study Information not displayed"""
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
    """TC-MENU-006 | Patch Placement item displayed"""
    open_menu(drv, wait=2.0)
    runner.assert_true(drv.is_visible_text("Patch Placement"), "Patch Placement not visible")
    close_menu(drv)


def test_menu_007_version_information_tap(drv, runner):
    """TC-MENU-007 | Tap Version Information → version info screen displayed"""
    open_menu(drv, wait=2.0)
    _tap_menu_item(drv, "Version Information")
    visible = drv.is_visible_text("Version", timeout=3)
    _ios_go_back(drv)          # sub-screen → menu screen
    close_menu(drv)            # menu screen → Step 1
    reset_to_step1(drv, hard=False)
    runner.assert_true(visible, "Version Information screen not opened")


def test_menu_008_patch_placement_tap(drv, runner):
    """TC-MENU-008 | Tap Patch Placement → placement guide screen displayed"""
    open_menu(drv, wait=2.0)
    _tap_menu_item(drv, "Patch Placement")
    time.sleep(1.0)
    visible = (
        drv.is_visible_text("Patch Placement", timeout=3)
        or drv.is_visible_text("Power Button", timeout=2)
        or drv.is_visible_text("Battery Side", timeout=2)
    )
    _ios_go_back(drv)          # sub-screen → menu screen
    close_menu(drv)            # menu screen → Step 1
    reset_to_step1(drv, hard=False)
    runner.assert_true(visible, "Patch Placement screen not opened")


def test_menu_009_back_returns_to_step1(drv, runner):
    """TC-MENU-009 | Close menu → Step 1 screen restored"""
    open_menu(drv, wait=2.0)
    close_menu(drv)
    # On iOS, React Native flat tree always contains Step 1 text in label.
    # Use TextField presence (Step 1 unique indicator) for accuracy.
    from appium.webdriver.common.appiumby import AppiumBy
    on_step1 = False
    try:
        els = drv.drv.find_elements(AppiumBy.IOS_PREDICATE, 'type == "XCUIElementTypeTextField"')
        on_step1 = bool(els)
    except Exception:
        pass
    if not on_step1:
        on_step1 = drv.is_visible_text("Connect Your S-Patch", timeout=2)
    runner.assert_true(on_step1, "Step 1 screen not restored after closing menu")


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
