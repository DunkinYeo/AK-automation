"""
TC-MENU-STUDY (iOS): Side menu regression tests during active study.
Mirrors menu_study.py but uses helpers_ios and ios_go_back instead of press_keycode(4).
"""
import time
import logging

from src.regression.helpers_ios import open_menu, close_menu, ios_go_back, _ratio_tap

log = logging.getLogger(__name__)

_NO_STUDY = "No study information"

# Menu row positions DURING STUDY (ratio of screen height, measured from
# screenshot on 375x812). During an active study the Terms and Information
# section gains Device/Study Information rows, pushing Patch Placement down —
# these differ from the disconnected-menu positions in menu_step1_ios.
# Flat RN tree: rows are not tappable elements — coordinate taps required.
_STUDY_MENU_ITEM_Y = {
    "Version Information": 0.373,
    "Device Information":  0.439,
    "Study Information":   0.504,
    "Patch Placement":     0.628,
}


def _tap_study_menu_item(drv, name: str):
    """Tap a menu row (during study) by measured coordinate."""
    _ratio_tap(drv, 0.50, _STUDY_MENU_ITEM_Y[name], f"menu item: {name}")
    time.sleep(1.5)


def test_menu_study_000_study_registered(drv, runner):
    """TC-MENU-STUDY-000 | Pre-check: study registered"""
    if drv.is_visible_text(_NO_STUDY, timeout=3):
        runner.fail("No study registered in web portal")


def test_menu_study_001_device_info_visible(drv, runner):
    """TC-MENU-STUDY-001 | Menu during study → Device Information visible"""
    if drv.is_visible_text(_NO_STUDY, timeout=2):
        return
    open_menu(drv, wait=2.5)
    try:
        runner.assert_true(
            drv.is_visible_text("Device Information", timeout=3),
            "Device Information not visible in menu during study"
        )
    finally:
        close_menu(drv)


def test_menu_study_002_study_info_visible(drv, runner):
    """TC-MENU-STUDY-002 | Menu during study → Study Information visible"""
    if drv.is_visible_text(_NO_STUDY, timeout=2):
        return
    open_menu(drv, wait=2.0)
    try:
        runner.assert_true(drv.is_visible_text("Version Information", timeout=3), "Menu did not open")
        runner.assert_true(
            drv.is_visible_text("Study Information", timeout=3),
            "Study Information not visible in menu during study"
        )
    finally:
        close_menu(drv)


def test_menu_study_003_sections_visible(drv, runner):
    """TC-MENU-STUDY-003 | All menu sections visible during study"""
    if drv.is_visible_text(_NO_STUDY, timeout=2):
        return
    open_menu(drv, wait=2.5)
    try:
        runner.assert_true(drv.is_visible_text("Setting",               timeout=3), "Setting not visible")
        runner.assert_true(drv.is_visible_text("Terms and Information", timeout=3), "Terms and Information not visible")
        runner.assert_true(drv.is_visible_text("Guide",                 timeout=3), "Guide not visible")
        runner.assert_true(drv.is_visible_text("Version Information",   timeout=3), "Version Information not visible")
        runner.assert_true(drv.is_visible_text("Patch Placement",       timeout=3), "Patch Placement not visible")
    finally:
        close_menu(drv)


def test_menu_study_004_study_info_tap(drv, runner):
    """TC-MENU-STUDY-004 | Study Information tap → study detail screen opens"""
    if drv.is_visible_text(_NO_STUDY, timeout=2):
        return
    open_menu(drv, wait=2.0)
    _tap_study_menu_item(drv, "Study Information")
    visible = (
        drv.is_visible_text("Study ID",       timeout=3)
        or drv.is_visible_text("Patient",     timeout=2)
        or drv.is_visible_text("Study Duration", timeout=2)
    )
    ios_go_back(drv)   # study info → menu
    close_menu(drv)    # menu → main (home icon)
    runner.assert_true(visible, "Study Information screen not opened")


def test_menu_study_005_device_info_tap(drv, runner):
    """TC-MENU-STUDY-005 | Device Information tap → device detail screen opens"""
    if drv.is_visible_text(_NO_STUDY, timeout=2):
        return
    open_menu(drv, wait=2.0)
    _tap_study_menu_item(drv, "Device Information")
    visible = (
        drv.is_visible_text("Device",   timeout=3)
        or drv.is_visible_text("Serial",   timeout=2)
        or drv.is_visible_text("Firmware", timeout=2)
    )
    ios_go_back(drv)   # device info → menu
    close_menu(drv)    # menu → main (home icon)
    runner.assert_true(visible, "Device Information screen not opened")


TESTS = [
    test_menu_study_000_study_registered,
    test_menu_study_001_device_info_visible,
    test_menu_study_002_study_info_visible,
    test_menu_study_003_sections_visible,
    test_menu_study_004_study_info_tap,
    test_menu_study_005_device_info_tap,
]
