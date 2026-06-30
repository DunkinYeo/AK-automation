import logging
import subprocess
import time

log = logging.getLogger(__name__)

from appium import webdriver
from appium.options.android.uiautomator2.base import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    InvalidSessionIdException,
)

from src.retry import retry
from src.artifacts import ArtifactManager
from src.reporter import RunReporter

# Substrings in exception messages that indicate the Appium session or ADB
# connection is gone rather than a normal UI timeout.
_SESSION_ERROR_PHRASES = (
    "invalid session id",
    "session not created",
    "no such session",
    "socket hang up",
    "connection reset",
    "connection refused",
    "adb connection",
    "broken pipe",
)


class AndroidDriver:
    def __init__(
        self,
        a_cfg: dict,
        selectors: dict,
        artifacts: ArtifactManager,
        reporter: RunReporter,
    ):
        self.cfg = a_cfg
        self.sel = selectors
        self.artifacts = artifacts
        self.reporter = reporter
        self._last_adb_reconnect_at: float = 0.0
        self.drv = self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _build_options(self) -> UiAutomator2Options:
        opts = UiAutomator2Options()
        opts.platform_name = "Android"
        opts.automation_name = "UiAutomator2"
        opts.device_name = self.cfg.get("device_name", "Android")
        opts.no_reset = bool(self.cfg.get("no_reset", True))
        opts.new_command_timeout = int(self.cfg.get("new_command_timeout", 3600))
        opts.stay_awake = True
        udid = self.cfg.get("udid", "")
        if not udid:
            # No UDID in config — try adb_wifi_device.json written by run.command/run.bat
            import json, os
            cache = "automation/runtime/adb_wifi_device.json"
            if os.path.exists(cache):
                try:
                    with open(cache) as _f:
                        _d = json.load(_f)
                    _ip = _d.get("wifi_ip", "")
                    _port = _d.get("tcp_port", 5555)
                    if _ip:
                        udid = f"{_ip}:{_port}"
                except Exception:
                    pass
        if udid:
            opts.udid = udid
        if self.cfg.get("app_package"):
            opts.app_package = self.cfg["app_package"]
        if self.cfg.get("app_activity"):
            opts.app_activity = self.cfg["app_activity"]
        return opts

    def _connect(self) -> webdriver.Remote:
        server = self.cfg.get("appium_server_url", "http://127.0.0.1:4723")
        self.reporter.log_event("appium_connect", {"server": server})
        return webdriver.Remote(server, options=self._build_options())

    def _ensure_adb_connected(self) -> None:
        """
        Re-establish WiFi ADB before creating a new Appium session.
        The ADB WiFi TCP connection is dropped when the host computer sleeps.
        Reads the cached address from automation/runtime/adb_wifi_device.json,
        or uses the UDID directly if it is already an ip:port address.
        Non-blocking — errors are logged but never raised.
        """
        import json
        import os

        udid = self.cfg.get("udid", "")
        wifi_addr = None

        # Case 1: UDID is already a WiFi address (ip:port, no leading slash)
        if udid and ":" in udid and not udid.startswith("/"):
            wifi_addr = udid

        # Case 2: read cached address written by run.command / run.bat
        if not wifi_addr:
            cache = "automation/runtime/adb_wifi_device.json"
            if os.path.exists(cache):
                try:
                    with open(cache) as f:
                        data = json.load(f)
                    ip = data.get("wifi_ip", "")
                    port = data.get("tcp_port", 5555)
                    if ip:
                        wifi_addr = f"{ip}:{port}"
                except Exception:
                    pass

        if not wifi_addr:
            return

        # Cooldown: skip if already attempted within the last 30 seconds.
        # Prevents duplicate reconnect calls within the same injection cycle
        # regardless of where ensure_session() is invoked.
        now = time.monotonic()
        if now - self._last_adb_reconnect_at < 30:
            return
        self._last_adb_reconnect_at = now

        try:
            self.reporter.log_event("adb_reconnect_attempt", {"addr": wifi_addr})
            result = subprocess.run(
                ["adb", "connect", wifi_addr],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip()
            self.reporter.log_event("adb_reconnect_result", {"addr": wifi_addr, "output": output})
            # Only sleep for a genuinely new connection, not "already connected"
            if "connected" in output.lower() and "already" not in output.lower():
                time.sleep(2)  # let ADB stabilize before Appium connects
        except Exception as e:
            self.reporter.log_event("adb_reconnect_failed", {"addr": wifi_addr, "error": str(e)})

    def reconnect(self):
        """
        Re-establish Appium session after a crash or timeout.
        Re-establishes the ADB WiFi connection first (dropped on host sleep),
        then creates a new Appium session and brings the app to foreground.
        """
        logging.warning("[SESSION] recreating driver")
        self.reporter.log_event("session_recreating", {})
        self._last_adb_reconnect_at = 0.0  # reset cooldown: real disconnection must always reconnect
        self._ensure_adb_connected()
        try:
            self.drv.quit()
        except Exception:
            pass
        self.drv = self._connect()
        try:
            self.bring_to_foreground()
        except Exception:
            pass
        logging.info("[SESSION] recovery success")
        self.reporter.log_event("session_recovery_success", {})

    def is_session_alive(self) -> bool:
        """
        Probe the Appium session by making a real network round-trip.
        current_activity exercises the underlying socket, so it will raise
        InvalidSessionIdException, WebDriverException (connection refused),
        or OSError (socket hang up / broken pipe) when the session is gone.
        """
        try:
            _ = self.drv.current_activity
            return True
        except Exception:
            return False

    def ensure_session(self):
        """Check session health; reconnect if dead.
        After host sleep/wake the ADB TCP connection drops, which makes
        is_session_alive() raise a socket/connection error → False.
        reconnect() then calls _ensure_adb_connected() to restore the
        WiFi ADB link before recreating the Appium session.
        """
        if not self.is_session_alive():
            logging.warning("[SESSION] driver lost — session not alive")
            self.reporter.log_event("session_lost", {"reason": "session_not_alive"})
            self.reconnect()

    def close(self):
        try:
            self.drv.quit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Locator helpers — priority: resource-id > content-desc > text > xpath
    # ------------------------------------------------------------------

    def _locators_for(self, value: str) -> list[tuple]:
        """
        Build a priority-ordered list of (By, selector) pairs for a given value.
        Callers can also pass a pre-built (By, selector) tuple directly.
        Note: ACCESSIBILITY_ID requires AppiumBy (not selenium By) since Appium 2.x.
        """
        return [
            (By.ID, value),                              # resource-id
            (AppiumBy.ACCESSIBILITY_ID, value),          # content-desc / accessibility-id
            (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{value}")'),
            (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{value}")'),
        ]

    def find(
        self,
        value: str,
        timeout: int = 10,
        contains: bool = False,
    ):
        """
        Find element trying priority order of selectors.
        If `contains=True`, skip resource-id/accessibility attempts and go
        straight to textContains (useful for partial text matches).
        """
        if contains:
            locator = (
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiSelector().textContains("{value}")',
            )
            return WebDriverWait(self.drv, timeout).until(
                EC.presence_of_element_located(locator)
            )

        per_locator = min(timeout, 2)
        last_exc = None
        tried: list[str] = []
        for locator in self._locators_for(value):
            tried.append(f"{locator[0]}={locator[1]}")
            try:
                return WebDriverWait(self.drv, per_locator).until(
                    EC.presence_of_element_located(locator)
                )
            except Exception as e:
                last_exc = e

        # Final wait with textContains as fallback
        final_locator = (
            AppiumBy.ANDROID_UIAUTOMATOR,
            f'new UiSelector().textContains("{value}")',
        )
        tried.append(f"textContains(full-timeout)={value}")
        try:
            return WebDriverWait(self.drv, timeout).until(
                EC.presence_of_element_located(final_locator)
            )
        except Exception as e:
            last_exc = e

        # All locators failed — log diagnostics before raising
        self._log_find_failure(value, tried)
        raise last_exc

    def _log_find_failure(self, value: str, tried: list[str]) -> None:
        """Log detailed diagnostics when find() exhausts all locators."""
        log.warning("[find] FAILED to locate '%s'", value)
        log.warning("[find] Tried %d locators: %s", len(tried), " | ".join(tried))
        try:
            info = self.get_device_info()
            log.warning("[find] Device: %s %s (Android %s) udid=%s",
                        info.get("manufacturer", "?"), info.get("model", "?"),
                        info.get("android_version", "?"), info.get("udid", "?"))
        except Exception:
            pass
        try:
            log.warning("[find] Activity: %s / %s",
                        self.drv.current_package, self.drv.current_activity)
        except Exception:
            pass
        try:
            tag = "find_fail_" + "".join(c if c.isalnum() else "_" for c in value)[:40]
            self.artifacts.screenshot(self.drv, tag)
            log.warning("[find] Screenshot saved: %s", tag)
        except Exception:
            pass
        try:
            page_src = self.drv.page_source
            tag = "find_fail_" + "".join(c if c.isalnum() else "_" for c in value)[:40]
            path = self.artifacts.save_text(tag + "_pagesource.xml", page_src)
            if path:
                log.warning("[find] Page source saved: %s", path)
        except Exception:
            pass

    # Legacy alias used by workflows
    def find_text(self, text: str, timeout: int = 10, contains: bool = False):
        return self.find(text, timeout=timeout, contains=contains)

    @retry(tries=3, delay=2)
    def tap_text(self, text: str | list, timeout: int = 10, contains: bool = True):
        texts = [text] if isinstance(text, str) else text
        per = max(timeout // len(texts), 2)
        last_exc: Exception = Exception(f"Could not find any of: {texts}")
        for t in texts:
            try:
                el = self.find(t, timeout=per, contains=contains)
                loc = el.location
                sz = el.size
                cx = loc["x"] + sz["width"] // 2
                cy = loc["y"] + sz["height"] // 2
                self.drv.tap([(cx, cy)])
                return True
            except Exception as e:
                last_exc = e
        raise last_exc

    def is_visible_text(self, text: str | list, contains: bool = True, timeout: int = 2) -> bool:
        texts = [text] if isinstance(text, str) else text
        for t in texts:
            try:
                self.find(t, timeout=timeout, contains=contains)
                return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # Session-safe action wrappers
    # ------------------------------------------------------------------

    def _is_session_error(self, exc: Exception) -> bool:
        """
        Return True if exc indicates a lost Appium session or ADB disconnect
        rather than a normal UI timeout or element-not-found error.
        Catches both typed exceptions and socket-level errors embedded in
        WebDriverException messages (e.g. "socket hang up", "connection reset").
        """
        if isinstance(exc, (InvalidSessionIdException, OSError)):
            return True
        msg = str(exc).lower()
        return any(phrase in msg for phrase in _SESSION_ERROR_PHRASES)

    def safe_tap(self, text: str | list, timeout: int = 10, contains: bool = True) -> bool:
        """
        tap_text wrapper that detects a lost session, recreates the driver,
        then retries the tap once. Use this for all UI taps in long-running
        workflows where the session may drop between interactions.

        Raises the original exception unchanged if the error is not session-related.
        """
        try:
            return self.tap_text(text, timeout=timeout, contains=contains)
        except Exception as exc:
            if self._is_session_error(exc):
                logging.warning("[SESSION] driver lost during tap — %s", exc)
                self.reporter.log_event("session_lost", {"action": "tap", "error": str(exc)})
                self.reconnect()
                return self.tap_text(text, timeout=timeout, contains=contains)
            raise

    def safe_send_keys(self, locator: str, text: str, timeout: int = 10) -> None:
        """
        find + send_keys wrapper that detects a lost session, recreates the
        driver, then retries the action once. Use this for all text input in
        long-running workflows.

        Raises the original exception unchanged if the error is not session-related.
        """
        try:
            el = self.find(locator, timeout=timeout)
            el.send_keys(text)
        except Exception as exc:
            if self._is_session_error(exc):
                logging.warning("[SESSION] driver lost during send_keys — %s", exc)
                self.reporter.log_event("session_lost", {"action": "send_keys", "error": str(exc)})
                self.reconnect()
                el = self.find(locator, timeout=timeout)
                el.send_keys(text)
            else:
                raise

    # ------------------------------------------------------------------
    # Artifact helpers
    # ------------------------------------------------------------------

    def screenshot(self, name: str) -> str:
        return self.artifacts.screenshot(self.drv, name)

    def logcat(self, name: str = "logcat") -> str:
        """
        Capture device logcat via ArtifactManager and emit reporter events.

        Returns the path to the saved log file on success, or None on failure.
        """
        seconds = 2
        try:
            self.reporter.log_event("artifact_logcat_start", {"name": name, "seconds": seconds})
        except Exception:
            # best-effort: don't fail if reporter logging errors
            pass

        try:
            path = self.artifacts.collect_android_logcat(name, seconds=seconds)
            if path:
                try:
                    self.reporter.log_event("artifact_logcat_done", {"name": name, "path": path})
                except Exception:
                    pass
            else:
                try:
                    self.reporter.log_event("artifact_logcat_failed", {"name": name, "error": "collect_android_logcat returned None"})
                except Exception:
                    pass
            return path
        except Exception as e:
            try:
                self.reporter.log_event("artifact_logcat_failed", {"name": name, "error": str(e)})
            except Exception:
                pass
            return None

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def bring_to_foreground(self):
        pkg = self.cfg.get("app_package")
        if not pkg:
            return
        # Dismiss any system popup blocking the app before activating
        self.dismiss_unexpected_popups()
        try:
            # activate_app resumes the app without recreating the Activity
            self.drv.activate_app(pkg)
        except Exception:
            # fallback: start_activity (may recreate Activity on some devices)
            act = self.cfg.get("app_activity")
            if act:
                try:
                    self.drv.start_activity(pkg, act)
                except Exception:
                    pass

    def recover_session(self, step: int = 1) -> bool:
        """
        Attempt to recover a stuck/frozen session in 3 escalating steps.
        Returns True if recovery succeeded, False otherwise.

        Args:
            step: 1 (back key), 2 (start_activity), or 3 (kill/relaunch)
        """
        pkg = self.cfg.get("app_package")
        act = self.cfg.get("app_activity")

        try:
            if step == 1:
                # Step 1: Send back key and wait for app to settle
                self.reporter.log_event("recovery_step_1", {"action": "press_back"})
                self.drv.press_keycode(4)  # KEYCODE_BACK
                self.wait_idle(1.0)
                return True

            elif step == 2:
                # Step 2: Force the app to foreground via activate_app
                self.reporter.log_event("recovery_step_2", {"action": "activate_app"})
                if pkg:
                    self.drv.activate_app(pkg)
                    self.wait_idle(1.5)
                    return True

            elif step == 3:
                # Step 3: Kill the app and restart it
                self.reporter.log_event("recovery_step_3", {"action": "kill_and_relaunch"})
                if pkg:
                    try:
                        self.drv.terminate_app(pkg)
                    except Exception:
                        pass
                    self.wait_idle(1.0)
                    try:
                        self.drv.activate_app(pkg)
                    except Exception:
                        if act:
                            self.drv.start_activity(pkg, act)
                    self.wait_idle(2.0)
                    return True

            return False
        except Exception as e:
            self.reporter.log_event(
                "recovery_failed",
                {"step": step, "error": str(e)},
            )
            # Re-raise so _attempt_recovery in scheduler.py can detect
            # UiAutomator2 instrumentation crashes and call reconnect().
            raise

    def wait_for_symptom_success(self, timeout: int = 10) -> str:
        """
        Wait for one of two success signals after symptom submission:
          1. symptom_success_signal_text  — configured toast/confirmation text
          2. symptom_add_text             — back on main measurement screen

        Returns the name of the signal that was detected first.
        Raises RuntimeError if neither appears within timeout.
        """
        success_signal = self.sel.get("symptom_success_signal_text")
        main_indicator = self.sel.get("symptom_add_text", "Add Symptom")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if success_signal and self.is_visible_text(success_signal):
                return "success_signal"
            if self.is_visible_text(main_indicator):
                return "main_screen"
            time.sleep(0.5)

        raise RuntimeError(
            f"Symptom success not confirmed within {timeout}s: "
            f"neither '{success_signal}' nor '{main_indicator}' appeared"
        )

    # ── Connectivity monitoring ──────────────────────────────────────────────
    # Known popup/state signatures — add new ones after live monitoring
    # ── Connectivity check definitions ──────────────────────────────────────
    # Text-based checks: detected when ANY candidate text is visible
    _CONN_TEXT_CHECKS = [
        ("connection_lost",   ["S-Patch connection lost"],   "S-Patch connection lost"),
        ("low_battery_patch", ["Low battery", "Battery low",
                               "Replace battery"],           "Patch low battery"),
        # --- add more after live monitoring ---
    ]

    # Inferred checks: detected by screen state (no direct popup text)
    # bluetooth_off: "Live ECG Signal" gone + "Patch Placement" visible
    # wifi_off: "Network" icon state — TBD after monitoring

    def check_connectivity(self):
        """
        Scan for connectivity issues. Emits events only on state transitions
        to avoid log spam. Runs every 30s via background thread.
        """
        if not hasattr(self, "_conn_state"):
            self._conn_state: dict[str, bool] = {}

        # Dismiss any unexpected system popups before checking UI state
        self.dismiss_unexpected_popups()

        # Text-based checks
        for event_name, texts, desc in self._CONN_TEXT_CHECKS:
            detected = any(self.is_visible_text(t, timeout=1) for t in texts)
            self._emit_conn_event(event_name, detected, desc)

        # Inferred: BT disconnected — on main screen but ECG section gone
        _main_indicator = self.sel.get("symptom_add_text", "Log Symptoms")
        on_main_screen = self.is_visible_text(_main_indicator, timeout=1)
        ecg_visible    = self.is_visible_text("Live ECG Signal", timeout=1)
        bt_disconnected = on_main_screen and not ecg_visible
        was_bt_off = self._conn_state.get("bluetooth_off", False)

        if bt_disconnected:
            self._emit_conn_event("bluetooth_off", True, "Bluetooth disconnected")
            if not was_bt_off:
                self._try_add_diary_bt_off()
                self._bt_disconnect_ts = time.time()
        elif was_bt_off and ecg_visible:
            # Positive confirmation: ECG signal visible again → genuinely reconnected
            self._emit_conn_event("bluetooth_off", False, "Bluetooth disconnected")
            if hasattr(self, "_bt_disconnect_ts"):
                elapsed = int(time.time() - self._bt_disconnect_ts)
                log.info("[connectivity] BT auto-reconnected after %ds", elapsed)
                self.reporter.log_event("bluetooth_reconnected", {
                    "elapsed_sec": elapsed,
                    "desc": f"Auto-reconnected after {elapsed}s"
                })
                del self._bt_disconnect_ts
                self._verify_ecg_after_reconnect()
        # else: was_bt_off=True but on a different screen — preserve disconnected state

        # WiFi off — detected via ADB settings (OS-level, reliable)
        wifi_off = self._adb_wifi_off()
        was_wifi_off = self._conn_state.get("wifi_off", False)
        self._emit_conn_event("wifi_off", wifi_off, "WiFi off")

        if wifi_off and not was_wifi_off:
            self._try_add_diary_wifi_off()
            self._wifi_off_ts = time.time()

        if not wifi_off and was_wifi_off and hasattr(self, "_wifi_off_ts"):
            elapsed = int(time.time() - self._wifi_off_ts)
            log.info("[connectivity] WiFi restored after %ds", elapsed)
            self.reporter.log_event("wifi_restored", {
                "elapsed_sec": elapsed,
                "desc": f"WiFi auto-restored after {elapsed}s"
            })
            del self._wifi_off_ts

        # Patch battery status — only readable when BT is connected.
        # When BT is off the app shows "How to Replace the Battery" guidance card,
        # which causes false "Replace" reads. Clear status on disconnect.
        if bt_disconnected:
            if self._conn_state.get("battery_status"):
                self._conn_state["battery_status"] = None
                self.reporter.log_event("battery_status", {"status": None})
        else:
            battery_status = None
            for label in ["Good", "Low", "Critical", "Replace", "Full"]:
                if self.is_visible_text(label, contains=False, timeout=1):
                    battery_status = label
                    break
            if battery_status and battery_status != self._conn_state.get("battery_status"):
                self._conn_state["battery_status"] = battery_status
                self.reporter.log_event("battery_status", {"status": battery_status})
                log.info("[connectivity] Patch battery status: %s", battery_status)

    # ── Unexpected popup handling ────────────────────────────────────────────

    # System packages that may steal focus with dialogs/permissions.
    _SYSTEM_POPUP_PKGS = {
        "android",
        "com.android.systemui",
        "com.android.packageinstaller",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.settings",
        "com.miui.securitycenter",        # Xiaomi
        "com.samsung.android.securitylogagent",  # Samsung
    }

    # Ordered dismiss attempts: (visible_text, log_label)
    # Ordered safest-first: ANR "Wait" before generic "OK"
    _POPUP_DISMISS_ORDER = [
        ("Wait",            "anr_wait"),           # ANR: keep app alive
        ("While using app", "permission_while_using"),
        ("Only this time",  "permission_once"),
        ("Allow",           "permission_allow"),
        ("Not now",         "dismiss_not_now"),
        ("Later",           "dismiss_later"),
        ("Dismiss",         "dismiss_dismiss"),
        ("Close",           "dismiss_close"),
        ("OK",              "dismiss_ok"),          # last resort — generic
    ]

    def _adb_focused_package(self) -> str:
        """Return the package name currently holding window focus via ADB."""
        import re
        try:
            udid = self.cfg.get("udid", "")
            cmd = ["adb"]
            if udid:
                cmd += ["-s", udid]
            cmd += ["shell", "dumpsys", "window", "windows"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            for line in result.stdout.splitlines():
                if "mCurrentFocus" in line:
                    m = re.search(r'([a-zA-Z][a-zA-Z0-9_.]+)/[a-zA-Z$]', line)
                    if m:
                        return m.group(1)
        except Exception as e:
            log.debug("[popup] focused_package check failed: %s", e)
        return ""

    def dismiss_unexpected_popups(self) -> bool:
        """
        Detect and dismiss unexpected system popups (permissions, ANR, etc.).
        Uses ADB to confirm a non-app package has focus before acting.
        Returns True if a popup was dismissed.
        Called in check_connectivity() every 30s and after bring_to_foreground().
        """
        our_pkg = self.cfg.get("app_package", "")
        focused_pkg = self._adb_focused_package()

        if not focused_pkg:
            return False  # couldn't determine focus — skip

        if focused_pkg == our_pkg:
            return False  # our app has focus — no popup

        if focused_pkg not in self._SYSTEM_POPUP_PKGS:
            # Unknown foreground package — log but don't act blindly
            log.info("[popup] unknown foreground package: %s", focused_pkg)
            self.reporter.log_event("unexpected_foreground", {
                "package": focused_pkg,
                "desc": "Unknown package in foreground",
            })
            return False

        # System package is in front — attempt dismiss
        log.info("[popup] system popup detected from: %s", focused_pkg)
        self.screenshot("popup_before_dismiss")

        for text, label in self._POPUP_DISMISS_ORDER:
            if self.is_visible_text(text, timeout=0.5):
                try:
                    self.tap_text(text, timeout=1)
                    time.sleep(0.5)
                    self.reporter.log_event("popup_dismissed", {
                        "package": focused_pkg,
                        "tapped":  text,
                        "label":   label,
                    })
                    log.info("[popup] dismissed via '%s' (%s) from %s", text, label, focused_pkg)
                    self.screenshot("popup_after_dismiss")
                    return True
                except Exception as e:
                    log.debug("[popup] tap '%s' failed: %s", text, e)

        # Nothing tappable — press back key as last resort
        try:
            self.drv.press_keycode(4)
            time.sleep(0.5)
            self.reporter.log_event("popup_dismissed", {
                "package": focused_pkg,
                "tapped":  "back_key",
                "label":   "back_key_fallback",
            })
            log.info("[popup] dismissed via back key from %s", focused_pkg)
            return True
        except Exception as e:
            log.debug("[popup] back key failed: %s", e)

        return False

    def wait_for_adb_device(self, timeout: int = 300) -> bool:
        """
        Poll ADB until device responds or timeout expires.
        Used by BT/airplane workflows to resume after disconnection.
        Returns True if device reconnected within timeout.
        """
        udid = self.cfg.get("udid", "")
        cmd = ["adb"] + (["-s", udid] if udid else []) + ["get-state"]
        deadline = time.time() + timeout
        self.reporter.log_event("adb_reconnect_wait", {"timeout_sec": timeout})
        log.info("[adb] Waiting for device reconnect (timeout=%ds)...", timeout)
        while time.time() < deadline:
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=5)
                if r.returncode == 0 and b"device" in r.stdout:
                    log.info("[adb] Device reconnected")
                    self.reporter.log_event("adb_reconnected", {})
                    return True
            except Exception:
                pass
            time.sleep(5)
        log.warning("[adb] Device did not reconnect within %ds", timeout)
        self.reporter.log_event("adb_reconnect_timeout", {"timeout_sec": timeout})
        return False

    def _adb_wifi_off(self) -> bool:
        """Check WiFi on/off state via ADB. Returns False on error (false negatives allowed)."""
        try:
            udid = self.cfg.get("udid", "")
            cmd = ["adb"]
            if udid:
                cmd += ["-s", udid]
            cmd += ["shell", "settings", "get", "global", "wifi_on"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.stdout.strip() == "0"
        except Exception as e:
            log.debug("[connectivity] wifi_off adb check failed: %s", e)
            return False

    def _try_add_diary_wifi_off(self):
        """Attempt symptom submission while WiFi is off — records whether it works."""
        import random as _random
        import time as _time
        from src.workflows.symptom_inject import SYMPTOMS
        _main_btn = self.sel.get("symptom_add_text", "Log Symptoms")
        _submit_btn = self.sel.get("log_symptoms_submit_text", "Save")
        try:
            log.info("[connectivity] WiFi off — attempting symptom submit")
            self.bring_to_foreground()
            if not self.is_visible_text(_main_btn, timeout=3):
                self.reporter.log_event("wifi_off_diary_result", {"result": f"{_main_btn!r} button not visible"})
                return
            symptom = _random.choice(SYMPTOMS)
            log.info("[connectivity] WiFi off symptom: %s", symptom)
            self.tap_text(_main_btn, timeout=3)
            _time.sleep(2.0)
            self.screenshot("connectivity_wifi_off_diary_opened")

            self.tap_text(symptom, timeout=8)
            _time.sleep(0.3)
            self.tap_text(_submit_btn, timeout=5)
            _time.sleep(1.5)
            self.screenshot("connectivity_wifi_off_diary_submitted")
            back_on_main = self.is_visible_text(_main_btn, timeout=3)
            self.reporter.log_event("wifi_off_diary_result", {
                "symptom": symptom,
                "result": "submitted and returned to main" if back_on_main else "submitted — screen changed",
            })
        except Exception as e:
            self.screenshot("connectivity_wifi_off_diary_error")
            log.warning("[connectivity] wifi_off_diary error: %s", e)
            self.reporter.log_event("wifi_off_diary_result", {"result": f"error: {e}"})

    def _verify_ecg_after_reconnect(self):
        """After reconnect, tap View → verify Live ECG Signal is displayed correctly."""
        import time as _time
        try:
            log.info("[connectivity] Verifying ECG signal after BT reconnect")
            if not self.is_visible_text("View", timeout=5):
                self.reporter.log_event("bt_reconnect_ecg_result", {"result": "View button not found"})
                return
            self.tap_text("View", timeout=5)
            _time.sleep(2.0)
            self.screenshot("connectivity_bt_reconnect_ecg")
            ecg_ok = self.is_visible_text("Live ECG Signal", timeout=5)
            self.reporter.log_event("bt_reconnect_ecg_result", {
                "result": "ECG signal visible" if ecg_ok else "ECG signal not visible"
            })
            # Back to main screen
            try:
                self.drv.press_keycode(4)
            except Exception:
                pass
        except Exception as e:
            self.reporter.log_event("bt_reconnect_ecg_result", {"result": f"error: {e}"})

    def _try_add_diary_bt_off(self):
        """Attempt symptom submission while BT is disconnected, then submit — records whether it works."""
        import random as _random
        import time as _time
        from src.workflows.symptom_inject import SYMPTOMS
        _main_btn = self.sel.get("symptom_add_text", "Log Symptoms")
        _submit_btn = self.sel.get("log_symptoms_submit_text", "Save")
        try:
            log.info("[connectivity] BT off — attempting symptom submit")
            self.bring_to_foreground()
            if not self.is_visible_text(_main_btn, timeout=3):
                self.reporter.log_event("bt_off_diary_result", {"result": f"{_main_btn!r} button not visible"})
                return
            symptom = _random.choice(SYMPTOMS)
            log.info("[connectivity] BT off symptom: %s", symptom)
            self.tap_text(_main_btn, timeout=3)
            _time.sleep(2.0)
            self.screenshot("connectivity_bt_off_diary_opened")

            self.tap_text(symptom, timeout=8)
            _time.sleep(0.3)
            self.tap_text(_submit_btn, timeout=5)
            _time.sleep(1.5)
            self.screenshot("connectivity_bt_off_diary_submitted")
            back_on_main = self.is_visible_text(_main_btn, timeout=3)
            self.reporter.log_event("bt_off_diary_result", {
                "symptom": symptom,
                "result": "submitted and returned to main" if back_on_main else "submitted — screen changed",
            })
        except Exception as e:
            self.screenshot("connectivity_bt_off_diary_error")
            log.warning("[connectivity] bt_off_diary error: %s", e)
            self.reporter.log_event("bt_off_diary_result", {"result": f"error: {e}"})

    def _emit_conn_event(self, event_name: str, detected: bool, desc: str):
        was = self._conn_state.get(event_name, False)
        if detected and not was:
            log.warning("[connectivity] %s detected", desc)
            try:
                self.screenshot(f"connectivity_{event_name}")
            except Exception:
                pass
            self.reporter.log_event(event_name, {"desc": desc})
        elif not detected and was:
            log.info("[connectivity] %s resolved", desc)
            self.reporter.log_event(f"{event_name}_resolved", {"desc": desc})
        self._conn_state[event_name] = detected

    def assert_ui_health(self):
        """
        Assert that the measurement running screen is visible.
        Uses symptom_add_text selector as the indicator (it's only visible
        when measurement is active and the screen is unobstructed).
        Raises RuntimeError if the indicator is not found — callers should
        treat this as a recoverable failure.
        """
        indicator = self.sel.get("symptom_add_text", "Add Symptom")
        self.reporter.log_event("ui_health_check", {"indicator": indicator})

        # Check connectivity issues before main health assertion
        try:
            self.check_connectivity()
        except Exception:
            pass

        if not self.is_visible_text(indicator):
            try:
                self.screenshot("ui_health_failed")
            except Exception:
                pass
            raise RuntimeError(f"UI health check failed: '{indicator}' not visible on screen")
        self.reporter.log_event("ui_health_ok", {"indicator": indicator})

    def wait_idle(self, seconds: float = 1.0):
        time.sleep(seconds)

    def get_device_info(self) -> dict:
        """Query model, manufacturer, Android version via adb shell getprop."""
        udid = self.cfg.get("udid", "")

        def _prop(name: str) -> str:
            try:
                cmd = ["adb"] + (["-s", udid] if udid else []) + ["shell", "getprop", name]
                return subprocess.check_output(cmd, timeout=5).decode().strip()
            except Exception:
                return ""

        return {
            "model": _prop("ro.product.model"),
            "manufacturer": _prop("ro.product.manufacturer"),
            "android_version": _prop("ro.build.version.release"),
            "udid": udid,
        }
