"""
IOSDriver — XCUITest-based driver for AccurKardia iOS automation.

Public interface mirrors AndroidDriver exactly so regression helpers
and workflow code can work with either driver without modification.

NEW FILE — does not modify src/driver.py (Android) in any way.
"""
import logging
import subprocess
import time

log = logging.getLogger(__name__)

from appium import webdriver
from appium.options.ios.xcuitest.base import XCUITestOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.remote.remote_connection import RemoteConnection
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    WebDriverException,
    InvalidSessionIdException,
)

from src.retry import retry
from src.artifacts import ArtifactManager
from src.reporter import RunReporter

_SESSION_ERROR_PHRASES = (
    "invalid session id",
    "session not created",
    "no such session",
    "socket hang up",
    "connection reset",
    "econnreset",
    "connection refused",
    "broken pipe",
    "could not proxy command",
)


class IOSDriver:
    def __init__(
        self,
        ios_cfg: dict,
        selectors: dict,
        artifacts: ArtifactManager,
        reporter: RunReporter,
    ):
        self.cfg = ios_cfg
        self.sel = selectors
        self.artifacts = artifacts
        self.reporter = reporter
        # #40: track the WDA/iproxy Popen handles this instance itself
        # started, so a reconnect can kill exactly those processes instead
        # of relying only on pattern-matched pkill (which left port 8100
        # occupied by a stale process 41 times in one 19h run).
        self._wda_proc = None
        self._iproxy_proc = None
        self.drv = self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @staticmethod
    def _wda_is_running(port: int = 8100) -> bool:
        """Return True if WDA is already serving on the given port."""
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/status", timeout=3
            ) as r:
                return r.status == 200
        except Exception:
            return False

    @staticmethod
    def _port_is_free(port: int) -> bool:
        """True if nothing accepts a TCP connection on localhost:port."""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return False  # something answered — occupied
        except Exception:
            return True
        finally:
            s.close()

    def _kill_tracked_wda_procs(self):
        """Kill exactly the WDA/iproxy processes *this instance* started
        (#40) — more reliable than the pattern-matched pkill below, which
        has no way to tell "a process this instance spawned" apart from
        an unrelated one, and left port 8100 occupied by a stale process
        41 times over one 19h run."""
        for attr in ("_wda_proc", "_iproxy_proc"):
            proc = getattr(self, attr, None)
            if proc is None:
                continue
            try:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
            except Exception:
                pass
            setattr(self, attr, None)

    def _start_wda_via_pymobiledevice3(self, wda_port: int = 8100) -> bool:
        """
        Start WDA on the device via pymobiledevice3 (userspace RSD, no root needed).
        Also starts iproxy to forward device:wda_port → localhost:wda_port.
        Returns True if WDA is accessible after startup.
        """
        wda_bundle = "com.facebook.WebDriverAgentRunner.xctrunner"
        udid = self.cfg.get("udid", "")

        # Kill this instance's own previous WDA/iproxy first (#40) — exact
        # and immediate, unlike the pattern-matched pkill below.
        self._kill_tracked_wda_procs()

        # Kill ALL stale tunnel/launcher leftovers before starting fresh.
        # The iproxy-only pkill missed a day-old `pymobiledevice3 … xcuitest`
        # zombie that kept WDA from ever becoming ready after a cable replug
        # (2026-07-09 incident — recovery spun for 40min; issue #1).
        for _pat in (f"iproxy.*{wda_port}",
                     f"pymobiledevice3 usbmux forward.*{wda_port}",
                     f"pymobiledevice3.*xcuitest.*{wda_bundle}"):
            try:
                subprocess.run(["pkill", "-f", _pat], capture_output=True)
            except Exception:
                pass

        # #40: a fixed sleep(0.5) didn't reliably confirm the OS had actually
        # released the port before the next WDA tried to bind it — that's
        # exactly what caused the repeated "port #8100 is occupied by an
        # other process" recovery failures. Poll instead, up to 5s.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self._port_is_free(wda_port):
            time.sleep(0.2)

        # Start port forwarding: iproxy (libimobiledevice) if available,
        # otherwise pymobiledevice3's built-in forwarder (pip-only, no brew)
        import shutil
        if shutil.which("iproxy"):
            iproxy_cmd = ["iproxy"]
            if udid:
                iproxy_cmd += ["-u", udid]
            iproxy_cmd.append(f"{wda_port}:{wda_port}")
            try:
                self._iproxy_proc = subprocess.Popen(
                    iproxy_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log.info("[driver-iOS] iproxy started: localhost:%d → device:%d", wda_port, wda_port)
            except Exception as e:
                log.warning("[driver-iOS] iproxy start failed: %s", e)
        else:
            from src.app_root import pymobiledevice3_argv
            fwd_cmd = pymobiledevice3_argv("usbmux", "forward", str(wda_port), str(wda_port))
            if udid:
                fwd_cmd += ["--udid", udid]
            try:
                self._iproxy_proc = subprocess.Popen(
                    fwd_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log.info("[driver-iOS] pymobiledevice3 forward started: localhost:%d → device:%d",
                         wda_port, wda_port)
            except Exception as e:
                log.warning("[driver-iOS] pymobiledevice3 forward failed: %s", e)

        # Start WDA via pymobiledevice3 dvt xcuitest (userspace, no root)
        from src.app_root import pymobiledevice3_argv
        wda_cmd = pymobiledevice3_argv(
            "developer", "dvt", "xcuitest",
            "--userspace",
            wda_bundle,
            "--env", f"USE_PORT={wda_port}",
            "--env", "MJPEG_SERVER_PORT=9100",
        )
        try:
            proc = subprocess.Popen(
                wda_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._wda_proc = proc
            log.info("[driver-iOS] WDA started via pymobiledevice3 (PID %d)", proc.pid)
        except Exception as e:
            log.warning("[driver-iOS] WDA pymobiledevice3 start failed: %s", e)
            return False

        # Wait up to 30s for WDA to be ready
        # 60s: a cold start after days idle exceeded 30s (2026-07-14);
        # warm starts return in a few seconds — early-exit poll
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self._wda_is_running(wda_port):
                log.info("[driver-iOS] WDA ready on port %d", wda_port)
                return True
            time.sleep(2)

        log.warning("[driver-iOS] WDA not ready after 60s on port %d", wda_port)
        return False

    def _build_options(self) -> XCUITestOptions:
        opts = XCUITestOptions()
        opts.platform_name = "iOS"
        opts.automation_name = "XCUITest"
        opts.device_name = self.cfg.get("device_name", "iPhone")
        opts.platform_version = self.cfg.get("platform_version", "18.6")
        opts.udid = self.cfg.get("udid", "")
        opts.bundle_id = self.cfg.get("bundle_id", "")
        opts.no_reset = bool(self.cfg.get("no_reset", True))
        opts.new_command_timeout = int(self.cfg.get("new_command_timeout", 3600))

        wda_port = self.cfg.get("wda_local_port", 8100)
        opts.set_capability("wdaLocalPort", wda_port)

        # Auto-dismiss iOS SYSTEM alerts (e.g. "iOS 18.7.8 설치되지 않음" OTA
        # failure at night) — such modals block every tap and stall the long
        # run until manually cleared (observed 2026-07-09 02:00-08:00).
        opts.set_capability("autoDismissAlerts", True)

        # Default to a fresh userspace WDA start. A stale-but-answering WDA can
        # accept session creation and then die with ECONNRESET during the suite.
        reuse_existing_wda = bool(self.cfg.get("reuse_existing_wda", False))
        if reuse_existing_wda and self._wda_is_running(wda_port):
            log.info("[driver-iOS] WDA already running on port %d — using webDriverAgentUrl", wda_port)
            opts.set_capability("webDriverAgentUrl", f"http://127.0.0.1:{wda_port}")
            opts.set_capability("usePrebuiltWDA", True)
            opts.set_capability("useNewWDA", False)
        elif self._start_wda_via_pymobiledevice3(wda_port):
            log.info("[driver-iOS] WDA started via pymobiledevice3 — using webDriverAgentUrl")
            opts.set_capability("webDriverAgentUrl", f"http://127.0.0.1:{wda_port}")
            opts.set_capability("usePrebuiltWDA", True)
            opts.set_capability("useNewWDA", False)
        else:
            log.warning("[driver-iOS] pymobiledevice3 WDA start failed — falling back to xcodebuild")
            # The pymobiledevice3 attempt above may have started iproxy/WDA
            # and then failed only the 60s readiness poll — those processes
            # can still be alive and holding wda_port, which would conflict
            # with Appium's own xcodebuild-launched WDA trying to bind the
            # same port right below (finding 2, code review 2026-07-31).
            self._kill_tracked_wda_procs()
            xcode_org_id = self.cfg.get("xcode_org_id", "")
            if xcode_org_id:
                opts.set_capability("xcodeOrgId", xcode_org_id)
                opts.set_capability("xcodeSigningId",
                                    self.cfg.get("xcode_signing_id", "Apple Development"))
            opts.set_capability("usePrebuiltWDA", False)
            opts.set_capability("useNewWDA", True)
            wda_launch_timeout = self.cfg.get("wda_launch_timeout", 60000)
            opts.set_capability("wdaLaunchTimeout", wda_launch_timeout)

        # Keep screen on during test
        opts.set_capability("keepKeyChains", True)

        if self.cfg.get("show_xcode_log"):
            opts.set_capability("showXcodeLog", True)

        return opts

    def _connect(self) -> webdriver.Remote:
        server = self.cfg.get("appium_server_url", "http://127.0.0.1:4723")
        # #34: see driver.py's _connect for the full rationale — without a
        # client-side timeout, a stalled Appium/WDA call blocks forever and
        # can deadlock the scheduler's shutdown.
        RemoteConnection.set_timeout(self.cfg.get("appium_http_timeout", 120))
        self.reporter.log_event("appium_connect_ios", {"server": server})
        return webdriver.Remote(server, options=self._build_options())

    def reconnect(self):
        log.warning("[SESSION-iOS] recreating driver")
        last_exc = None
        for attempt in range(1, 4):
            self.reporter.log_event("session_recreating_ios", {"attempt": attempt})
            try:
                self.drv.quit()
            except Exception:
                pass
            try:
                self.drv = self._connect()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        self.drv.get_window_size()
                        break
                    except Exception as e:
                        last_exc = e
                        time.sleep(1)
                else:
                    raise last_exc or RuntimeError("iOS session did not become ready")
                try:
                    self._activate_app()
                    self.wait_idle(1.0)
                    self.drv.get_window_size()
                except Exception as e:
                    if self._is_session_error(e):
                        last_exc = e
                        continue
                    raise
                log.info("[SESSION-iOS] recovery success")
                self.reporter.log_event("session_recovery_success_ios", {"attempt": attempt})
                return
            except Exception as e:
                last_exc = e
                log.warning("[SESSION-iOS] recovery attempt %d failed: %s", attempt, e)
                self.reporter.log_event("session_recovery_attempt_failed_ios", {
                    "attempt": attempt,
                    "error": str(e),
                })
                time.sleep(2)
        raise last_exc or RuntimeError("iOS session recovery failed")

    def is_session_alive(self) -> bool:
        try:
            if not getattr(self.drv, "session_id", None):
                return False
            self.drv.get_window_size()
            return True
        except Exception:
            return False

    def ensure_session(self):
        if not self.is_session_alive():
            log.warning("[SESSION-iOS] driver lost — reconnecting")
            self.reporter.log_event("session_lost_ios", {"reason": "session_not_alive"})
            self.reconnect()

    def close(self):
        try:
            self.drv.quit()
        except Exception:
            pass
        # #40: drv.quit() only ends the Appium session over HTTP — it never
        # touched the WDA/iproxy subprocesses this instance actually
        # spawned, which is exactly what caused the *next* run's cold start
        # to find port 8100 still occupied.
        self._kill_tracked_wda_procs()

    # ------------------------------------------------------------------
    # Locator helpers
    # iOS priority: ACCESSIBILITY_ID → predicate exact → predicate contains
    # ------------------------------------------------------------------

    def _locators_for(self, value: str) -> list[tuple]:
        return [
            (AppiumBy.ACCESSIBILITY_ID, value),
            (AppiumBy.IOS_PREDICATE, f'label == "{value}"'),
            (AppiumBy.IOS_PREDICATE, f'value == "{value}"'),
            (AppiumBy.IOS_PREDICATE, f'name == "{value}"'),
        ]

    def find(self, value: str, timeout: int = 10, contains: bool = False):
        """
        Find element trying iOS locator priority order.
        Same interface as AndroidDriver.find().
        """
        if contains:
            locator = (AppiumBy.IOS_PREDICATE, f'label CONTAINS "{value}"')
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

        # Final: full-timeout contains fallback
        final_locator = (AppiumBy.IOS_PREDICATE, f'label CONTAINS "{value}"')
        tried.append(f"label_contains(full)={value}")
        try:
            return WebDriverWait(self.drv, timeout).until(
                EC.presence_of_element_located(final_locator)
            )
        except Exception as e:
            last_exc = e

        self._log_find_failure(value, tried)
        raise last_exc

    def _log_find_failure(self, value: str, tried: list[str]) -> None:
        log.warning("[find-iOS] FAILED to locate '%s'", value)
        log.warning("[find-iOS] Tried %d locators: %s", len(tried), " | ".join(tried))
        try:
            info = self.get_device_info()
            log.warning("[find-iOS] Device: %s (iOS %s) udid=%s",
                        info.get("model", "?"), info.get("ios_version", "?"),
                        info.get("udid", "?"))
        except Exception:
            pass
        try:
            log.warning("[find-iOS] Bundle: %s", self.drv.current_package)
        except Exception:
            pass
        try:
            tag = "find_fail_" + "".join(c if c.isalnum() else "_" for c in value)[:40]
            self.artifacts.screenshot(self.drv, tag)
            log.warning("[find-iOS] Screenshot saved: %s", tag)
        except Exception:
            pass
        try:
            page_src = self.drv.page_source
            tag = "find_fail_" + "".join(c if c.isalnum() else "_" for c in value)[:40]
            path = self.artifacts.save_text(tag + "_pagesource.xml", page_src)
            if path:
                log.warning("[find-iOS] Page source saved: %s", path)
        except Exception:
            pass

    # Legacy alias
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
                el.click()
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
    # Session-safe wrappers (same interface as AndroidDriver)
    # ------------------------------------------------------------------

    def _is_session_error(self, exc: Exception) -> bool:
        if isinstance(exc, (InvalidSessionIdException, OSError)):
            return True
        msg = str(exc).lower()
        return any(phrase in msg for phrase in _SESSION_ERROR_PHRASES)

    def safe_tap(self, text: str | list, timeout: int = 10, contains: bool = True) -> bool:
        try:
            return self.tap_text(text, timeout=timeout, contains=contains)
        except Exception as exc:
            if self._is_session_error(exc):
                log.warning("[SESSION-iOS] driver lost during tap — %s", exc)
                self.reporter.log_event("session_lost_ios", {"action": "tap", "error": str(exc)})
                self.reconnect()
                return self.tap_text(text, timeout=timeout, contains=contains)
            raise

    # ------------------------------------------------------------------
    # Artifact helpers
    # ------------------------------------------------------------------

    def screenshot(self, name: str) -> str:
        return self.artifacts.screenshot(self.drv, name)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _activate_app(self):
        bundle_id = self.cfg.get("bundle_id", "")
        if bundle_id:
            self.drv.activate_app(bundle_id)

    def bring_to_foreground(self):
        try:
            self._activate_app()
        except Exception as e:
            if self._is_session_error(e):
                log.warning("[SESSION-iOS] driver lost during activate_app — reconnecting: %s", e)
                self.reporter.log_event("session_lost_ios", {
                    "action": "activate_app",
                    "error": str(e),
                })
                self.reconnect()
            else:
                raise
        self.dismiss_unexpected_popups()

    def dismiss_unexpected_popups(self) -> bool:
        """
        Dismiss common iOS system dialogs (permissions, alerts).
        No ADB needed — uses Appium text detection.
        """
        dismissed = False
        # Native system alert (e.g. nightly OTA-update failure "iOS x.x 설치되지
        # 않음") — blocks all taps; accept via WDA alert API first
        try:
            self.drv.execute_script("mobile: alert", {"action": "accept"})
            time.sleep(0.5)
            log.info("[popup-iOS] system alert accepted via mobile: alert")
            self.reporter.log_event("popup_dismissed_ios", {"tapped": "(system alert)"})
            dismissed = True
        except Exception:
            pass
        # iOS permission + system dialog buttons (safest-first order)
        for text in ["Allow While Using App", "Allow", "Only This Time",
                     "Continue", "OK", "Close", "Dismiss", "확인", "Don't Allow"]:
            if self.is_visible_text(text, timeout=0.5):
                try:
                    self.tap_text(text, timeout=1)
                    time.sleep(0.5)
                    log.info("[popup-iOS] dismissed via '%s'", text)
                    self.reporter.log_event("popup_dismissed_ios", {"tapped": text})
                    dismissed = True
                    break
                except Exception:
                    pass
        return dismissed

    def recover_session(self, step: int = 1) -> bool:
        bundle_id = self.cfg.get("bundle_id", "")
        try:
            if not self.is_session_alive():
                self.reconnect()
                return True
            if step == 1:
                # iOS: swipe from left edge as back gesture
                size = self.drv.get_window_size()
                self.drv.swipe(0, size["height"] // 2,
                               size["width"] // 3, size["height"] // 2, 300)
                self.wait_idle(1.0)
                return True
            elif step == 2:
                if bundle_id:
                    self.drv.activate_app(bundle_id)
                    self.wait_idle(1.5)
                    return True
            elif step == 3:
                if bundle_id:
                    try:
                        self.drv.terminate_app(bundle_id)
                    except Exception:
                        pass
                    self.wait_idle(1.0)
                    self.drv.activate_app(bundle_id)
                    self.wait_idle(2.0)
                    return True
            return False
        except Exception as e:
            self.reporter.log_event("recovery_failed_ios", {"step": step, "error": str(e)})
            if self._is_session_error(e):
                log.warning("[SESSION-iOS] driver lost during recovery step %s — reconnecting: %s",
                            step, e)
                self.reconnect()
                return True
            raise

    def wait_for_symptom_success(self, timeout: int = 10) -> str:
        success_signal = self.sel.get("symptom_success_signal_text")
        main_indicator = self.sel.get("symptom_add_text", "Add Diary")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if success_signal and self.is_visible_text(success_signal):
                return "success_signal"
            if self.is_visible_text(main_indicator):
                return "main_screen"
            time.sleep(0.5)
        raise RuntimeError(
            f"Symptom success not confirmed within {timeout}s"
        )

    def assert_ui_health(self):
        indicator = self.sel.get("symptom_add_text", "Add Diary")
        self.reporter.log_event("ui_health_check_ios", {"indicator": indicator})
        try:
            self.dismiss_unexpected_popups()
        except Exception as e:
            if self._is_session_error(e):
                self.reconnect()
            else:
                raise
        if not self.is_visible_text(indicator):
            if self._detect_study_completed():
                raise RuntimeError(
                    "study completed — app is on the Study Overview screen")
            try:
                from src.regression.helpers_ios import go_to_main
                log.info("[health-iOS] '%s' not visible — navigating back to main screen", indicator)
                go_to_main(self)
                self.wait_idle(2.0)
                self.dismiss_unexpected_popups()
            except Exception as e:
                if self._is_session_error(e):
                    self.reconnect()
                else:
                    log.warning("[health-iOS] main-screen recovery attempt failed: %s", e)
            if self.is_visible_text(indicator):
                self.reporter.log_event("ui_health_ok_ios", {"indicator": indicator})
                return
            if self._detect_study_completed():
                raise RuntimeError(
                    "study completed — app is on the Study Overview screen")
            try:
                self.screenshot("ui_health_failed_ios")
            except Exception:
                pass
            raise RuntimeError(f"UI health check failed: '{indicator}' not visible")

    def _detect_study_completed(self) -> bool:
        """
        Detect the post-study 'Study Overview' screen (issue #18 — iOS
        mirror of AndroidDriver._detect_study_completed, issue #11).
        Sets self._study_completed so LongRunScheduler's until_study_end
        early-exit (checked directly via getattr(driver, "_study_completed",
        False)) and the scheduler's job-skip logic both work without any
        further iOS-specific code. Emits the study_completed event once.
        Never raises.

        Text/structure captured from a real device (iPhone 13 mini, iOS
        18.6.2) reaching this screen naturally on 2026-07-31: the XCUITest
        tree uses `label="..."` (not Android's `text="..."`) on
        XCUIElementTypeStaticText nodes, with each value in its own
        adjacent element right after its label — e.g. label="Study" is
        immediately followed by a separate label="100" node. Matching is
        by text content and tree adjacency, not screen coordinates, so it
        should hold across other iPhone screen sizes in principle — but
        this has only been verified against this one physical device;
        there was no second iPhone available to confirm across devices
        the way the Android version was (Pixel 7 + a Samsung device).
        """
        if getattr(self, "_study_completed", False):
            return True
        try:
            if not self.is_visible_text("Study Overview", contains=True, timeout=2):
                return False
            # "Your study has been completed. Please return the device to
            # the provider." is the confirmed exact message on this screen —
            # anchor on "completed" rather than the iOS-specific "Ok" button
            # label, since an incomplete-upload variant (if one exists on
            # iOS, mirroring Android's Upload/Skip state) hasn't been
            # observed yet to confirm its exact wording.
            if not self.is_visible_text("completed", contains=True, timeout=2):
                return False
            import re as _re
            src = self.drv.page_source

            def _grab(pattern):
                m = _re.search(pattern, src, _re.S)
                return m.group(1) if m else None

            info = {
                "study_percent": _grab(r'label="Study"[^>]*>.{0,1500}?label="(\d{1,3})"'),
                "upload_percent": _grab(r'label="Data Upload"[^>]*>.{0,1500}?label="(\d{1,3})"'),
                "study_start": _grab(r'label="Start Time"[^>]*>.{0,1500}?label="(\d{4}-\d{2}-\d{2} [\d:]{8})"'),
                "study_end": _grab(r'label="End Time"[^>]*>.{0,1500}?label="(\d{4}-\d{2}-\d{2} [\d:]{8})"'),
            }
            self._study_completed = True
            try:
                self.screenshot("study_overview_completed_ios")
            except Exception:
                pass
            self.reporter.log_event("study_completed_ios", info)
            log.warning("[study-iOS] App study completed (upload %s%%, %s ~ %s) — "
                        "remaining scheduled jobs will be skipped",
                        info["upload_percent"], info["study_start"], info["study_end"])
            return True
        except Exception as e:
            log.debug("[study-iOS] completed-screen check failed: %s", e)
            return False
        self.reporter.log_event("ui_health_ok_ios", {"indicator": indicator})

    def wait_idle(self, seconds: float = 1.0):
        time.sleep(seconds)

    def get_device_info(self) -> dict:
        udid = self.cfg.get("udid", "")
        model = ""
        ios_version = ""
        try:
            cmd = ["ideviceinfo", "-u", udid, "-k", "ProductType"] if udid else ["ideviceinfo", "-k", "ProductType"]
            model = subprocess.check_output(cmd, timeout=5).decode().strip()
        except Exception:
            pass
        try:
            cmd = ["ideviceinfo", "-u", udid, "-k", "ProductVersion"] if udid else ["ideviceinfo", "-k", "ProductVersion"]
            ios_version = subprocess.check_output(cmd, timeout=5).decode().strip()
        except Exception:
            ios_version = self.cfg.get("platform_version", "")
        return {
            "model": model or self.cfg.get("device_name", "iPhone"),
            "manufacturer": "Apple",
            "ios_version": ios_version,
            "udid": udid,
        }

    # ------------------------------------------------------------------
    # Stubs for Android-only features (no-op on iOS)
    # ------------------------------------------------------------------

    def check_connectivity(self):
        pass

    def wait_for_adb_device(self, timeout: int = 300) -> bool:
        return True
