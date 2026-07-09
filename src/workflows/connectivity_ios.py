"""
iOS BT-disconnect / Airplane-mode workflows via Control Center UI automation.

NEW FILE — mirrors src/workflows/bt_disconnect.py and airplane_mode.py without
modifying them. iOS has no ADB equivalent, so system toggles are driven through
Control Center, whose toggles ARE exposed as real elements (system UI — no
React Native flat-tree problem).

Verified on iPhone 13 mini, iOS 18.6.2, Korean locale (2026-07-07):
  - Open CC:    W3C swipe from top-right corner (x≈95% w, y=1) down to ~50% h
  - CC has pages (iOS 18): the connectivity page holds the toggles; if not
    visible after opening, tap the antenna page icon at ratio (0.948, 0.565)
  - Airplane:   Button/Switch label "에어플레인 모드" (or "Airplane Mode"),
                Switch value "0"/"1"
  - Bluetooth:  Button label "Bluetooth"; its value shows the connected device
                name (e.g. "S-Patch EX 510131") — used to verify BLE state.
                NOTE: the CC Bluetooth tile DISCONNECTS devices ("disconnect
                until tomorrow") rather than fully powering BT off — sufficient
                to simulate the S-Patch going out of range.
  - Close CC:   home gesture (swipe up from bottom edge)
"""
import logging
import os
import time

from appium.webdriver.common.appiumby import AppiumBy

log = logging.getLogger(__name__)

_TICK = 5  # seconds per poll tick during waits

_AIRPLANE_LABELS  = ["에어플레인 모드", "Airplane Mode"]
_BLUETOOTH_LABELS = ["Bluetooth", "블루투스"]

# Connectivity page icon in the CC page rail (right edge), ratio of screen
_CC_PAGE_ICON = (0.948, 0.565)


def _wall_sleep(seconds: float) -> None:
    """Sleep for wall-clock seconds, robust to host sleep/wake."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_TICK, remaining))


def _w3c_swipe(d, x1, y1, x2, y2, duration_ms=500):
    """Perform a W3C pointer swipe (works outside the AUT, unlike mobile: swipe)."""
    d.drv.execute(
        "actions",
        {"actions": [{
            "type": "pointer", "id": "finger1",
            "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "x": int(x1), "y": int(y1)},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": 100},
                {"type": "pointerMove", "duration": duration_ms, "x": int(x2), "y": int(y2)},
                {"type": "pointerUp", "button": 0},
            ],
        }]},
    )


def _find_cc_element(d, labels, el_type="Button"):
    """Find a Control Center element by any of the given labels."""
    for label in labels:
        try:
            els = d.drv.find_elements(
                AppiumBy.IOS_PREDICATE,
                f'type == "XCUIElementType{el_type}" AND label == "{label}"',
            )
            if els:
                return els[0]
        except Exception:
            pass
    return None


def _set_active_app(d, bundle: str):
    """
    Point WDA's element queries at the given app ("com.apple.springboard" or
    "auto"). REQUIRED: an Appium session bound to the AUT keeps snapshotting
    the AUT even while Control Center is visually open — queries return the
    app tree and CC elements are never found (verified 2026-07-07).
    """
    try:
        d.drv.update_settings({"defaultActiveApplication": bundle})
    except Exception as e:
        log.warning("[connectivity-ios] update_settings failed: %s", e)


def _open_control_center(d) -> bool:
    """Open Control Center on the connectivity page. Returns True on success."""
    size = d.drv.get_window_size()
    w, h = size["width"], size["height"]
    _w3c_swipe(d, w * 0.95, 1, w * 0.95, h * 0.5)
    time.sleep(1.5)
    # Make element queries target springboard (Control Center), not the AUT
    _set_active_app(d, "com.apple.springboard")
    time.sleep(0.5)
    if _find_cc_element(d, _AIRPLANE_LABELS) or _find_cc_element(d, _BLUETOOTH_LABELS):
        return True
    # iOS 18 CC pages: navigate to the connectivity page via its rail icon
    try:
        d.drv.execute_script("mobile: tap", {
            "x": int(w * _CC_PAGE_ICON[0]), "y": int(h * _CC_PAGE_ICON[1]),
        })
    except Exception:
        _w3c_swipe(d, w * _CC_PAGE_ICON[0], h * _CC_PAGE_ICON[1],
                   w * _CC_PAGE_ICON[0], h * _CC_PAGE_ICON[1], duration_ms=80)
    time.sleep(1.2)
    return bool(_find_cc_element(d, _AIRPLANE_LABELS) or _find_cc_element(d, _BLUETOOTH_LABELS))


def _close_control_center(d):
    """Close Control Center, restore AUT-targeted queries, re-activate the app."""
    _set_active_app(d, "auto")
    size = d.drv.get_window_size()
    w, h = size["width"], size["height"]
    _w3c_swipe(d, w * 0.5, h - 2, w * 0.5, h * 0.5, duration_ms=400)
    time.sleep(1.0)
    try:
        bundle_id = d.cfg.get("bundle_id", "")
        if bundle_id:
            d.drv.activate_app(bundle_id)
            time.sleep(1.5)
    except Exception:
        pass


def _airplane_state(d):
    """Return airplane switch state: True(on)/False(off)/None(unknown)."""
    sw = _find_cc_element(d, _AIRPLANE_LABELS, el_type="Switch")
    if sw is None:
        sw = _find_cc_element(d, _AIRPLANE_LABELS, el_type="Button")
    if sw is None:
        return None
    val = sw.get_attribute("value")
    if val in ("1", "켬", "On", "on"):
        return True
    if val in ("0", "끔", "Off", "off"):
        return False
    return None


def _bt_connected_device(d) -> str:
    """Return the device name shown on the CC Bluetooth tile ('' if none)."""
    btn = _find_cc_element(d, _BLUETOOTH_LABELS, el_type="Button")
    if btn is None:
        return ""
    return btn.get_attribute("value") or ""


# ── Settings-app Bluetooth toggle ────────────────────────────────────────────
# The CC Bluetooth tile only "disconnects accessories" and leaves the radio ON;
# CoreBluetooth app connections (the S-Patch BLE link) survive it (verified
# 2026-07-07: app stayed connected through a full CC-tile disconnect cycle).
# The ONLY automatable full-off is the Settings app switch. Also note: iOS
# silently re-enables Bluetooth when AirDrop or similar features are used.

_SETTINGS_BUNDLE = "com.apple.Preferences"
_BT_DEEPLINK     = "App-Prefs:Bluetooth"


def _open_bt_settings(d) -> bool:
    """Open Settings > Bluetooth page. Deep link first, then UI nav fallback."""
    # Deep link works in CLI sessions; may fail in web-created Appium sessions
    try:
        d.drv.get(_BT_DEEPLINK)
        time.sleep(2.0)
        if _bt_switch(d) is not None:
            return True
    except Exception:
        pass

    # Fallback: relaunch Settings from scratch (terminate resets it to the
    # root page — otherwise it can restore a sub-page where neither the
    # switch nor the root Bluetooth row is visible), then tap the row.
    try:
        d.drv.execute_script("mobile: terminateApp", {"bundleId": _SETTINGS_BUNDLE})
        time.sleep(1.0)
    except Exception:
        pass
    try:
        d.drv.execute_script("mobile: launchApp", {"bundleId": _SETTINGS_BUNDLE})
    except Exception:
        try:
            d.drv.activate_app(_SETTINGS_BUNDLE)
        except Exception:
            pass
    time.sleep(2.0)

    if _bt_switch(d) is not None:
        return True

    # Navigate from Settings home → Bluetooth sub-page
    try:
        for pred in (
            'label == "Bluetooth" AND type == "XCUIElementTypeCell"',
            'label == "Bluetooth" AND type == "XCUIElementTypeStaticText"',
            'label == "Bluetooth" OR label == "블루투스"',
        ):
            els = d.drv.find_elements(AppiumBy.IOS_PREDICATE, pred)
            if els:
                els[0].click()
                time.sleep(1.5)
                break
    except Exception:
        pass

    if _bt_switch(d) is not None:
        return True
    _log_bt_settings_failure(d)
    return False


def _log_bt_settings_failure(d):
    """Record what the device was actually showing when navigation failed."""
    try:
        info = d.drv.execute_script("mobile: activeAppInfo") or {}
        log.warning("[connectivity-ios] BT settings nav failed — active app: %s",
                    info.get("bundleId", "?"))
    except Exception:
        pass
    try:
        os.makedirs("runtime", exist_ok=True)
        path = time.strftime("runtime/bt_settings_fail_%Y%m%d_%H%M%S.png")
        d.drv.save_screenshot(path)
        log.warning("[connectivity-ios] Failure screenshot: %s", path)
    except Exception:
        pass


def _bt_switch(d):
    """Return the Bluetooth switch element on the Settings > Bluetooth page."""
    try:
        els = d.drv.find_elements(
            AppiumBy.IOS_PREDICATE,
            'type == "XCUIElementTypeSwitch" AND '
            '(label == "Bluetooth" OR label == "블루투스")',
        )
        if els:
            return els[0]
    except Exception:
        pass
    return None


def _bt_switch_state(d):
    """True(on)/False(off)/None(unknown) from the Settings Bluetooth switch."""
    sw = _bt_switch(d)
    if sw is None:
        return None
    return (sw.get_attribute("value") or "") == "1"


def _set_bluetooth(d, on: bool) -> bool:
    """Set the Bluetooth radio via the Settings switch. Returns success."""
    if not _open_bt_settings(d):
        log.warning("[connectivity-ios] Settings Bluetooth page not reachable")
        return False
    state = _bt_switch_state(d)
    if state == on:
        return True
    sw = _bt_switch(d)
    sw.click()
    time.sleep(2.0)
    return _bt_switch_state(d) == on


def _back_to_app(d):
    """Re-activate the AUT after Settings work."""
    try:
        bundle_id = d.cfg.get("bundle_id", "")
        if bundle_id:
            d.drv.activate_app(bundle_id)
            time.sleep(1.5)
    except Exception:
        pass


def _app_bt_card(d) -> str:
    """
    Read the app's Bluetooth status card text ('Connected'/'Disconnected'/'').
    NOTE (2026-07-07): with the BT radio fully OFF the iOS app kept showing
    "Connected" for 60+ seconds — suspected APP BUG. Logged for reporting,
    NOT used as the pass/fail signal.
    """
    try:
        src = d.drv.page_source
        import re
        m = re.search(r"Bluetooth[^A-Za-z]{0,40}(Connected|Disconnected)", src)
        if m:
            return m.group(1)
        if "Disconnected" in src:
            return "Disconnected"
        if "Connected" in src:
            return "Connected"
    except Exception:
        pass
    return ""


def _set_airplane(d, on: bool) -> bool:
    """Toggle airplane mode inside an already-open Control Center."""
    state = _airplane_state(d)
    if state is None:
        log.warning("[connectivity-ios] Airplane toggle not found in Control Center")
        return False
    if state == on:
        log.info("[connectivity-ios] Airplane already %s", "ON" if on else "OFF")
        return True
    el = (_find_cc_element(d, _AIRPLANE_LABELS, el_type="Switch")
          or _find_cc_element(d, _AIRPLANE_LABELS, el_type="Button"))
    el.click()
    time.sleep(2.0)
    return _airplane_state(d) == on


def ensure_bluetooth_on(driver) -> bool:
    """
    Pre-run guard: make sure the BT radio is ON before starting tests
    (leftover experiment state / iOS 'disconnect until tomorrow' transitions
    can leave it off and break 950-popup TCs and BLE connection).
    """
    try:
        ok = _set_bluetooth(driver, True)
        _back_to_app(driver)
        if ok:
            log.info("[connectivity-ios] Pre-run BT check: ON")
        else:
            log.warning("[connectivity-ios] Pre-run BT check FAILED — continuing anyway")
        return ok
    except Exception as e:
        log.warning("[connectivity-ios] Pre-run BT check error: %s", e)
        _back_to_app(driver)
        return False


def run_bt_disconnect(driver, disconnect_minutes: float) -> None:
    """
    Turn the Bluetooth RADIO fully off for `disconnect_minutes`, then back on,
    via the Settings app switch (the only method that actually kills the
    S-Patch BLE link — the CC tile does not). Emits the same reporter events
    as the Android workflow.
    """
    driver.reporter.log_event("bt_disconnect_start", {"minutes": disconnect_minutes})
    log.info("[bt_disconnect-ios] Turning Bluetooth OFF for %.1f min (Settings switch)",
             disconnect_minutes)

    if not _set_bluetooth(driver, False):
        driver.reporter.log_event("bt_disconnect_failed",
                                  {"phase": "disable", "error": "Settings BT switch off failed"})
        _back_to_app(driver)
        return
    log.info("[bt_disconnect-ios] BT switch confirmed OFF")
    driver.reporter.log_event("bluetooth_off", {"method": "settings_switch"})

    # Observe the app's Bluetooth card (known issue: may keep showing Connected)
    _back_to_app(driver)
    time.sleep(5)
    card = _app_bt_card(driver)
    log.info("[bt_disconnect-ios] App BT card 5s after radio off: %r "
             "(app-bug watch: expected Disconnected)", card)
    driver.reporter.log_event("bt_app_card_after_off", {"card": card})

    _wall_sleep(disconnect_minutes * 60 - 5)

    if not _set_bluetooth(driver, True):
        driver.reporter.log_event("bt_disconnect_failed",
                                  {"phase": "enable", "error": "Settings BT switch on failed"})
        _back_to_app(driver)
        return
    log.info("[bt_disconnect-ios] BT switch confirmed ON")
    driver.reporter.log_event("bluetooth_reconnected", {"method": "settings_switch"})
    _back_to_app(driver)

    time.sleep(10)
    card = _app_bt_card(driver)
    driver.reporter.log_event("bt_disconnect_done", {
        "minutes": disconnect_minutes,
        "app_card_after_restore": card,
    })
    log.info("[bt_disconnect-ios] BT re-enabled after %.1f min (app card: %r)",
             disconnect_minutes, card)


def run_airplane_mode(driver, airplane_minutes: float) -> None:
    """
    Enable airplane mode for `airplane_minutes`, then disable.
    Safe on iOS: WDA runs over the USB tunnel (pymobiledevice3/iproxy),
    which airplane mode does not cut.
    """
    driver.reporter.log_event("airplane_mode_start", {"minutes": airplane_minutes})
    log.info("[airplane_mode-ios] Enabling airplane mode for %.1f min", airplane_minutes)

    if not _open_control_center(driver):
        driver.reporter.log_event("airplane_mode_failed",
                                  {"phase": "enable", "error": "Control Center not reachable"})
        _close_control_center(driver)
        return
    if not _set_airplane(driver, True):
        driver.reporter.log_event("airplane_mode_failed",
                                  {"phase": "enable", "error": "airplane toggle failed"})
        _close_control_center(driver)
        return
    _close_control_center(driver)

    # Observe app status cards (iOS may keep WiFi/BT on in airplane mode)
    time.sleep(5)
    try:
        src = driver.drv.page_source
        driver.reporter.log_event("airplane_app_state", {
            "disconnected_shown": "Disconnected" in src,
        })
    except Exception:
        pass
    _wall_sleep(airplane_minutes * 60 - 5)

    if not _open_control_center(driver):
        driver.reporter.log_event("airplane_mode_failed",
                                  {"phase": "disable", "error": "Control Center not reachable"})
        _close_control_center(driver)
        return
    ok = _set_airplane(driver, False)
    # Airplane-off does not always restore BT connections immediately; log tile state
    bt_after = _bt_connected_device(driver)
    _close_control_center(driver)

    if not ok:
        driver.reporter.log_event("airplane_mode_failed",
                                  {"phase": "disable", "error": "airplane toggle failed"})
        return

    driver.reporter.log_event("airplane_mode_done", {
        "minutes": airplane_minutes,
        "bt_tile_after": bt_after,
    })
    log.info("[airplane_mode-ios] Airplane mode disabled after %.1f min (BT tile: %r)",
             airplane_minutes, bt_after)
