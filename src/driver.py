import logging
import subprocess
import threading
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
def _read_wifi_cache() -> str | None:
    """
    Return the cached WiFi ADB address ('ip:port') written by run.command/
    run.bat/web, or None. Tries every known layout — the old single
    cwd-relative path matched NO layout (dev repo, dist zip, web cwd), so
    the cache fallback had effectively never worked (review #2, issue #2):
      1. <code root>/runtime/…      (dev repo AND dist automation/ dir)
      2. <cwd>/runtime/…            (zip root — where run.bat/run.command write)
      3. <cwd>/automation/runtime/… (legacy path, kept for compatibility)
    """
    import json as _json
    from pathlib import Path as _Path
    here = _Path(__file__).resolve()
    for cache in (here.parent.parent / "runtime" / "adb_wifi_device.json",
                  _Path("runtime/adb_wifi_device.json"),
                  _Path("automation/runtime/adb_wifi_device.json")):
        try:
            if cache.exists():
                data = _json.loads(cache.read_text(encoding="utf-8"))
                ip = data.get("wifi_ip", "")
                port = data.get("tcp_port", 5555)
                if ip:
                    return f"{ip}:{port}"
        except Exception:
            continue
    return None


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
            # No UDID in config — try the WiFi cache written by run.command/
            # run.bat/web (multi-layout resolution, issue #2)
            cached = _read_wifi_cache()
            if cached:
                udid = cached
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

        # Case 2: read cached address written by run.command / run.bat / web
        # (multi-layout resolution, issue #2 — the old single relative path
        # matched no layout, so sleep/wake WiFi reconnect never worked)
        if not wifi_addr:
            wifi_addr = _read_wifi_cache()

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

    # Serializes session recreation across threads (scheduler recovery vs
    # monitor self-heal) — concurrent reconnects thrash (2026-07-10)
    _reconnect_lock = threading.RLock()

    def reconnect(self):
        """
        Re-establish Appium session after a crash or timeout.
        Re-establishes the ADB WiFi connection first (dropped on host sleep),
        then creates a new Appium session and brings the app to foreground.
        Thread-safe: serialized via _reconnect_lock.
        """
        with self._reconnect_lock:
            self._reconnect_locked()

    def _reconnect_locked(self):
        logging.warning("[SESSION] recreating driver")
        self.reporter.log_event("session_recreating", {})
        self._last_adb_reconnect_at = 0.0  # reset cooldown: real disconnection must always reconnect
        self._ensure_adb_connected()
        # USB after host sleep: the device may not have re-enumerated yet —
        # creating a session before ADB sees it again fails instantly
        # (tester incident 2026-07-09, issue #6). USB only: a WiFi device
        # reappears via the adb-connect above, never by waiting.
        udid = self.cfg.get("udid", "")
        is_wifi = ":" in udid and not udid.startswith("/")
        if not is_wifi and not self._adb_device_present():
            self.wait_for_adb_device(timeout=300)
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

    def ensure_ui_automation(self):
        """Probe the UiAutomator2 proxy, not just Appium's ADB-backed session.

        Appium can still answer current_activity/current_package while the
        UiAutomator2 instrumentation process is dead. Connectivity monitoring
        depends on UI queries, so force one proxied call and reconnect if it
        cannot reach UiAutomator2.
        """
        try:
            self.drv.find_elements(By.CLASS_NAME, "android.widget.TextView")
        except Exception as e:
            logging.warning("[SESSION] UiAutomator2 proxy lost — recreating driver")
            self.reporter.log_event("uiautomator_proxy_lost", {"error": str(e)})
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

    # ── Device screen keep-awake ─────────────────────────────────────────
    # stay_awake=True only holds WHILE CHARGING — Pixel battery protection
    # paused charging mid-soak (2026-07-11 ~16:59) so the screen timed out
    # and locked, killing every UI-based job for 39h while ADB-based cycles
    # kept passing. These helpers are charging-independent.

    def _adb_cmd(self) -> list:
        udid = self.cfg.get("udid", "")
        return ["adb"] + (["-s", udid] if udid else [])

    def screen_is_on(self) -> bool:
        """True if the display is on. Unknown → True (never over-trigger wakes)."""
        try:
            r = subprocess.run(self._adb_cmd() + ["shell", "dumpsys", "display"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                if "mScreenState" in line:
                    return "ON" in line
        except Exception:
            pass
        return True

    def wake_screen(self):
        """Wake + dismiss the (swipe) lockscreen. No-op if already on."""
        try:
            subprocess.run(self._adb_cmd() + ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
                           capture_output=True, timeout=10)
            time.sleep(1.0)
            subprocess.run(self._adb_cmd() + ["shell", "wm", "dismiss-keyguard"],
                           capture_output=True, timeout=10)
            time.sleep(1.0)
            self.reporter.log_event("screen_waked", {})
            log.warning("[screen] display was OFF — waked + keyguard dismissed")
        except Exception as e:
            log.warning("[screen] wake failed: %s", e)

    def ensure_screen_on(self):
        """ADB-only check-and-wake; safe from any thread."""
        if not self.screen_is_on():
            self.wake_screen()

    def get_screen_timeout(self) -> str:
        """Current system screen_off_timeout as a string ('' on error)."""
        try:
            r = subprocess.run(self._adb_cmd() + ["shell", "settings", "get", "system", "screen_off_timeout"],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip()
        except Exception:
            return ""

    def set_screen_timeout(self, ms: int) -> str:
        """Set system screen_off_timeout; returns the previous value ('' on error)."""
        try:
            r = subprocess.run(self._adb_cmd() + ["shell", "settings", "get", "system", "screen_off_timeout"],
                               capture_output=True, text=True, timeout=10)
            old = r.stdout.strip()
            subprocess.run(self._adb_cmd() + ["shell", "settings", "put", "system", "screen_off_timeout", str(ms)],
                           capture_output=True, timeout=10)
            self.reporter.log_event("screen_timeout_set", {"ms": ms, "previous": old})
            return old
        except Exception as e:
            log.warning("[screen] timeout set failed: %s", e)
            return ""

    def check_app_process(self, allow_relaunch: bool = True):
        """
        Detect the AUT process dying mid-run (field reports: app crashes
        during use). Pure ADB, no UI interaction — safe to call at any
        time, including during injections (where crashes are most likely).

        allow_relaunch=False records the crash but leaves relaunching to
        the scheduler job path (used while a job/BT/airplane owns the
        device, so the watch never fights an in-flight flow).

        Guards (code review 2026-07-10):
          - ADB health is verified first — an offline/unauthorized adb
            must not be mistaken for an app crash (false process_gone)
          - restarts caused by our own recovery (kill_and_relaunch) are
            expected: recover_session sets _expect_app_restart and the
            pid change is then NOT reported as a field crash
        """
        pkg = self.cfg.get("app_package", "")
        if not pkg:
            return
        if not self._adb_device_present():
            return  # ADB unhealthy — cannot judge the app; skip this tick
        udid = self.cfg.get("udid", "")
        adb = ["adb"] + (["-s", udid] if udid else [])
        try:
            r = subprocess.run(adb + ["shell", "pidof", "-s", pkg],
                               capture_output=True, text=True, timeout=10)
            pid = r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return  # adb hiccup — let the next tick decide
        last = getattr(self, "_app_pid_last", None)

        # Expected-restart flag lifecycle (review 2026-07-10 #2): the flag
        # must be consumed on EVERY app-comes-back path and must expire —
        # a stale flag would hide the next real crash forever.
        expect = getattr(self, "_expect_app_restart", False)
        if expect and time.time() - getattr(self, "_expect_app_restart_ts", 0) > 300:
            expect = self._expect_app_restart = False  # stale (>5min) — stop suppressing

        if pid:
            if last and pid != last:
                if expect:
                    self._expect_app_restart = False  # our recovery did it
                else:
                    log.warning("[app-watch] app restarted silently (pid %s → %s)", last, pid)
                    self.reporter.log_event("app_crashed", {
                        "kind": "silent_restart", "pid_before": last, "pid_after": pid,
                        "evidence": self._save_crash_evidence(),
                    })
            elif last is None:
                if expect:
                    self._expect_app_restart = False  # back after our kill — consume
                if getattr(self, "_crash_pending", False):
                    # Close the pairing: a recorded process_gone crash is now
                    # back alive (job recovery / OS restarted it) — without
                    # this the report renders a successful recovery as
                    # "relaunch failed" (review 2026-07-10 #3)
                    self._crash_pending = False
                    self.reporter.log_event("app_relaunched_after_crash",
                                            {"by": "job_recovery_or_system"})
            self._app_pid_last = pid
            self._app_alive_device_ts = self._device_now(adb)
            return

        if last is None:
            return  # never seen alive yet — nothing to compare against

        if expect:
            return  # our recovery's kill window — not a field crash; await relaunch

        log.warning("[app-watch] app process GONE (was pid %s) — saving evidence%s",
                    last, ", relaunching" if allow_relaunch else " (relaunch deferred to job recovery)")
        self.reporter.log_event("app_crashed", {
            "kind": "process_gone", "pid_before": last,
            "evidence": self._save_crash_evidence(),
            "relaunch": "monitor" if allow_relaunch else "deferred_to_job_recovery",
        })
        self._app_pid_last = None
        self._crash_pending = True  # closed by the next alive tick or below
        if not allow_relaunch:
            return
        try:
            self.bring_to_foreground()
            self._crash_pending = False
            self.reporter.log_event("app_relaunched_after_crash", {"by": "monitor"})
        except Exception as e:
            log.warning("[app-watch] relaunch failed (next job's recovery will retry): %s", e)

    @staticmethod
    def _device_now(adb: list) -> str:
        """Device-clock 'MM-DD HH:MM:SS' (logcat timestamps use device time)."""
        try:
            r = subprocess.run(adb + ["shell", "date", "+%m-%d %H:%M:%S"],
                               capture_output=True, text=True, timeout=5)
            return r.stdout.strip()
        except Exception:
            return ""

    def _save_crash_evidence(self) -> str:
        """
        Save crash evidence for the app team. Primary file = crash-buffer
        lines SINCE the last tick the app was seen alive (device clock) —
        the raw buffer keeps old crashes for days (a 2026-07-01 crash was
        still in the Pixel 7 buffer), which would muddy the evidence.
        The unfiltered buffer is saved alongside as *_full.log.
        """
        udid = self.cfg.get("udid", "")
        adb = ["adb"] + (["-s", udid] if udid else [])
        try:
            r = subprocess.run(adb + ["logcat", "-b", "crash", "-d"],
                               capture_output=True, text=True, timeout=15)
            full = (r.stdout or "").strip()
            if not full:
                return ""
            stamp = time.strftime("%Y%m%d_%H%M%S")
            since = getattr(self, "_app_alive_device_ts", "")
            recent = self._crash_lines_since(full, since) if since else ""
            full_path = self.artifacts.save_text(f"app_crash_{stamp}_full.log", full)
            if recent:
                return self.artifacts.save_text(f"app_crash_{stamp}.log", recent)
            return full_path  # can't scope by time — full buffer is the evidence
        except Exception as e:
            log.warning("[app-watch] crash-log capture failed: %s", e)
            return ""

    @staticmethod
    def _crash_lines_since(buffer_text: str, since_ts: str) -> str:
        """Return buffer lines at/after 'MM-DD HH:MM:SS' (lexicographic on
        logcat's zero-padded timestamps; header lines are kept with what
        follows them)."""
        out, keep = [], False
        for line in buffer_text.splitlines():
            ts = line[:14]  # 'MM-DD HH:MM:SS'
            if len(ts) == 14 and ts[2] == "-" and ts[5] == " ":
                keep = ts >= since_ts
            if keep:
                out.append(line)
        return "\n".join(out).strip()

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

        # Screen-off is unrecoverable by back/activate/relaunch — wake first.
        # (39h of 3-step failures on 2026-07-11..13 were exactly this.)
        try:
            self.ensure_screen_on()
        except Exception:
            pass

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
                self._expect_app_restart = True  # app-watch: this restart is ours, not a field crash
                self._expect_app_restart_ts = time.time()
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

        # Inferred: BT disconnected.
        #
        # Do not use "Live ECG Signal" absence as the primary signal: that
        # text is only visible on the Real-time ECG tab, so the normal Device
        # Status / My Study Progress view can otherwise look disconnected.
        # Prefer explicit OS/app signals:
        #   - phone Bluetooth is actually off (scheduled BT workflow)
        #   - AK shows the disconnected status/guidance (natural patch drop)
        _main_indicator = self.sel.get("symptom_add_text", "Log Symptoms")
        on_main_screen = self.is_visible_text(_main_indicator, timeout=1)
        phone_bt_off = self._adb_bt_off()
        wifi_off = self._adb_wifi_off()
        bt_guidance_visible = any(
            self.is_visible_text(t, contains=True, timeout=1)
            for t in (
                "Bluetooth not enabled",
                "Cannot find your S-Patch",
                "Reset your S-Patch",
                "Attacth",
                "Attach the S-Patch",
            )
        )
        bt_status_disconnected = (
            on_main_screen
            and not wifi_off
            and self.is_visible_text("Bluetooth", contains=True, timeout=1)
            and self.is_visible_text("Disconnected", contains=True, timeout=1)
        )
        bt_disconnected = phone_bt_off or bt_guidance_visible or bt_status_disconnected
        bt_source = (
            "phone_bluetooth_off" if phone_bt_off
            else "ak_bt_guidance" if bt_guidance_visible
            else "ak_bt_status_disconnected" if bt_status_disconnected
            else "none"
        )
        was_bt_off = self._conn_state.get("bluetooth_off", False)

        if bt_disconnected:
            self._emit_conn_event("bluetooth_off", True, f"Bluetooth disconnected ({bt_source})")
            if not was_bt_off and phone_bt_off:
                self._try_add_diary_bt_off()
                self._bt_disconnect_ts = time.time()
            elif not was_bt_off:
                self._bt_disconnect_ts = time.time()
        elif was_bt_off and not bt_disconnected:
            # Positive confirmation: explicit disconnected signals are gone.
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
        # which causes false "Replace" reads. Use ADB as ground truth to guard
        # against cases where UI detection misses a natural BT disconnection.
        bt_actually_off = bt_disconnected or phone_bt_off
        if bt_actually_off:
            if self._conn_state.get("battery_status"):
                self._conn_state["battery_status"] = None
                self.reporter.log_event("battery_status", {"status": None})
        else:
            battery_status = None
            # "How to Replace the Battery" card is always on screen (card 4).
            # If "Replace" is the matched label, verify it's not from card 4
            # by confirming "How to" is NOT visible alongside it.
            how_to_visible = self.is_visible_text("How to", contains=True, timeout=1)
            for label in ["Good", "Low", "Critical", "Full", "Replace"]:
                if self.is_visible_text(label, contains=False, timeout=1):
                    if label == "Replace" and how_to_visible:
                        break  # "Replace" is from card 4, not battery status
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

    def _adb_device_present(self) -> bool:
        """Quick non-waiting check that ADB currently sees the device."""
        udid = self.cfg.get("udid", "")
        cmd = ["adb"] + (["-s", udid] if udid else []) + ["get-state"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=5)
            return r.returncode == 0 and b"device" in r.stdout
        except Exception:
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

    def _adb_bt_off(self) -> bool:
        """Check BT on/off state via ADB. Returns False on error (false negatives allowed)."""
        try:
            udid = self.cfg.get("udid", "")
            cmd = ["adb"]
            if udid:
                cmd += ["-s", udid]
            cmd += ["shell", "settings", "get", "global", "bluetooth_on"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.stdout.strip() == "0"
        except Exception as e:
            log.debug("[connectivity] bt_off adb check failed: %s", e)
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
            self.reporter.log_event("regression_diary_saved",
                                    {"symptom": symptom, "source": "connectivity-wifi-off"})
        except Exception as e:
            self.screenshot("connectivity_wifi_off_diary_error")
            log.warning("[connectivity] wifi_off_diary error: %s", e)
            self.reporter.log_event("wifi_off_diary_result", {"result": f"error: {e}"})

    def _verify_ecg_after_reconnect(self):
        """After reconnect, tap View → verify Live ECG Signal is displayed correctly."""
        import time as _time
        try:
            log.info("[connectivity] Verifying ECG signal after BT reconnect")
            # If the patch link is still down (radio restored but the patch
            # is away/out of range), "no View button" is the EXPECTED state —
            # report the real cause instead of a misleading UI failure
            # (2026-07-10 16:11: radio-restore resolved the BT state while
            # the patch was physically separated)
            if (self.is_visible_text("Bluetooth", contains=True, timeout=2)
                    and self.is_visible_text("Disconnected", contains=True, timeout=2)):
                self.reporter.log_event("bt_reconnect_ecg_result",
                                        {"result": "patch link still down — ECG check skipped"})
                return
            # The current app main screen opens on the Device Status tab,
            # which has no View button at all (2026-07-15 screenshot: BT
            # Connected / Battery Good, still no View) — the ECG lives on
            # the Real-time ECG tab. Switch tabs before looking for it.
            switched = False
            if self.is_visible_text("Real-time ECG", timeout=3):
                try:
                    self.tap_text("Real-time ECG", timeout=3)
                    _time.sleep(2.0)
                    switched = True
                except Exception:
                    pass
            # Poll in rounds instead of one long wait: right after BT toggles
            # a transient session error makes a single wait raise instantly
            # (→ returned False in 0s despite timeout=20, seen 16:11:20).
            # Rounds tolerate one-off hiccups; early-exit when found.
            result = None
            viewed = False
            for _ in range(3):
                if self.is_visible_text("Live ECG Signal", timeout=4):
                    result = "ECG signal visible"
                    break
                # Legacy layout: signal is behind a View button
                if self.is_visible_text("View", timeout=3):
                    try:
                        self.tap_text("View", timeout=5)
                        viewed = True
                        _time.sleep(2.0)
                    except Exception:
                        pass
                    result = ("ECG signal visible"
                              if self.is_visible_text("Live ECG Signal", timeout=5)
                              else "ECG signal not visible")
                    break
                _time.sleep(1)
            self.screenshot("connectivity_bt_reconnect_ecg")
            if result is None:
                on_main = self.is_visible_text(
                    self.sel.get("symptom_add_text", "Log Symptoms"), timeout=3)
                self.reporter.log_event("bt_reconnect_ecg_result", {
                    "result": "ECG view not found",
                    "on_main_screen": on_main,
                    "tab_switched": switched,
                })
            else:
                self.reporter.log_event("bt_reconnect_ecg_result", {"result": result})
            # Restore: leave the View screen, then back to Device Status tab
            try:
                if viewed:
                    self.drv.press_keycode(4)
                    _time.sleep(0.8)
                if switched and self.is_visible_text("Device Status", timeout=2):
                    self.tap_text("Device Status", timeout=2)
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
            self.reporter.log_event("regression_diary_saved",
                                    {"symptom": symptom, "source": "connectivity-bt-off"})
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
            # Study finished? The app replaces the main screen with the
            # Study Overview (Upload/Skip) screen — that's a terminal state,
            # not a UI failure (issue #11, observed 2026-07-16).
            if self._detect_study_completed():
                raise RuntimeError(
                    "study completed — app is on the Study Overview screen")
            try:
                self.screenshot("ui_health_failed")
            except Exception:
                pass
            raise RuntimeError(f"UI health check failed: '{indicator}' not visible on screen")
        self.reporter.log_event("ui_health_ok", {"indicator": indicator})
        self._report_study_progress()

    def _detect_study_completed(self) -> bool:
        """
        Detect the post-study 'Study Overview' screen and scrape what the
        tester reports to QA: Data Upload %, study start/end (issue #11).
        Sets self._study_completed so the scheduler can skip the remaining
        jobs instead of recording hourly fake failures. Emits the
        study_completed event once. Never raises.
        """
        if getattr(self, "_study_completed", False):
            return True
        try:
            if not self.is_visible_text("Study Overview", contains=True, timeout=2):
                return False
            if not (self.is_visible_text("Upload", timeout=2)
                    or self.is_visible_text("Skip", timeout=2)):
                return False
            import re as _re
            src = self.drv.page_source
            # Node XML runs ~600 chars per element — window must span to the
            # next node's text attribute (verified live 2026-07-16)
            def _grab(pattern):
                m = _re.search(pattern, src, _re.S)
                return m.group(1) if m else None
            info = {
                "study_percent": _grab(r'text="Study".{0,1500}?text="(\d{1,3})"'),
                "upload_percent": _grab(r'text="Data Upload".{0,1500}?text="(\d{1,3})"'),
                "study_start": _grab(r'text="Start Time".{0,1500}?text="(\d{4}-\d{2}-\d{2} [\d:]{8})"'),
                "study_end": _grab(r'text="End Time".{0,1500}?text="(\d{4}-\d{2}-\d{2} [\d:]{8})"'),
            }
            self._study_completed = True
            try:
                self.screenshot("study_overview_completed")
            except Exception:
                pass
            self.reporter.log_event("study_completed", info)
            log.warning("[study] App study completed (upload %s%%, %s ~ %s) — "
                        "remaining scheduled jobs will be skipped",
                        info["upload_percent"], info["study_start"], info["study_end"])
            # Upload incomplete → tester must tap Upload in the app; Slack
            # heads-up so they know without watching the phone (issue #13)
            up = info["upload_percent"]
            webhook = getattr(self, "_slack_webhook", "")
            if webhook and up is not None and up != "100":
                try:
                    from src.slack import slack_notify
                    slack_notify(webhook,
                                 f"🩺 App study completed — Data Upload {up}%. "
                                 f"ACTION REQUIRED: tap 'Upload' in the app to "
                                 f"finish uploading the study data.")
                except Exception:
                    pass
            return True
        except Exception as e:
            log.debug("[study] completed-screen check failed: %s", e)
            return False

    def _report_study_progress(self):
        """
        Read 'My Study Progress N%' from the main screen (issue #10).
        The app/patch study runs on its own schedule, independent of the web
        run duration — surface its percent so the dashboard can show both,
        and flag once at >=95% so the run owner knows remaining injections
        will hit a completed study. Best-effort: never raises, and emits
        nothing when the text can't be read.
        """
        try:
            if not self.is_visible_text("My Study Progress", contains=True, timeout=2):
                return
            import re as _re
            src = self.drv.page_source
            pct = None
            m = _re.search(r'text="(\d{1,3})\s*%"', src)
            if m:
                pct = int(m.group(1))
            else:
                # Split rendering ("99" + "%"): standalone number right after
                # the progress-card label. Node XML runs ~600 chars per
                # element, so the window must span past a full node
                # (2026-07-16 live: 400 was too short — 0% never emitted)
                m = _re.search(r'text="My Study Progress".{0,1500}?text="(\d{1,3})"',
                               src, _re.S)
                if m:
                    pct = int(m.group(1))
            if pct is None or not (0 <= pct <= 100):
                return
            if pct != getattr(self, "_last_study_pct", None):
                self._last_study_pct = pct
                self.reporter.log_event("study_progress", {"percent": pct})
                log.info("[study] App study progress: %d%%", pct)
            if pct >= 95 and not getattr(self, "_study_warned", False):
                self._study_warned = True
                self._study_warn_pending = pct  # consumed by main.py → Slack
                self.reporter.log_event("study_end_warning", {"percent": pct})
                log.warning("[study] App study at %d%% — it will finish before "
                            "the automation run; later injections may fail", pct)
        except Exception as e:
            log.debug("[study] progress read skipped: %s", e)

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
