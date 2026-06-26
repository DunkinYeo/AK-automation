#!/usr/bin/env python3
"""
S-Patch VM Full Automation Runner

Single entry point for SDK validation. Runs the following flow in order:

  1. App restart → Step 1
  2. [Regression] serial + menu
  3. Serial input → Connect → Step 2
  4. [Regression] signal (Step 2 screen)
  5. Continue → Step 3 (Review Study Setting)
  6. Continue → Start Study → measurement start
  7. [Regression] main + diary + menu-study
  8. Symptom injection schedule (for duration_hours)
  9. Final Slack report

Usage:
    PYTHONPATH=. python src/run.py --config config/spatch-vm.yaml
    PYTHONPATH=. python src/run.py --config config/spatch-vm.yaml --dry-run
"""
import argparse
import datetime
import logging
import os
import random
import sys
import threading
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

from src.artifacts import ArtifactManager
from src.reporter import RunReporter
from src.driver import AndroidDriver
from src.keep_awake import KeepAwake
from src.scheduler import LongRunScheduler
from src.slack import slack_daily_report, slack_bug_report, slack_urgent_alert, slack_injection_notify, slack_regression_suite
from src.regression.runner import TestRunner
from src.regression import serial_input, menu_step1, signal_check, main_screen, add_diary, menu_study, connectivity
from src.regression.helpers import reset_to_step1, open_menu
from src.workflows.symptom_inject import inject_symptom_event, SYMPTOMS, ACTIVITIES
from src.workflows.bt_disconnect import run_bt_disconnect
from src.workflows.airplane_mode import run_airplane_mode
from src.workflows.popup_handler import handle_any_popup
from selenium.webdriver.common.by import By
from appium.webdriver.common.appiumby import AppiumBy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

_STEP1_TEXT  = "Connect Your S-Patch"
_STEP2_TEXT  = "Check Incoming Signal"
_STEP3_TEXT  = "Review Study Setting"
_START_TEXT  = "Start Study"
_MAIN_TEXT   = "Log Symptoms"


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

def _has_text(drv, text: str) -> bool:
    """UiAutomator textContains immediate check — no wait, no exception."""
    try:
        return len(drv.drv.find_elements(
            AppiumBy.ANDROID_UIAUTOMATOR,
            f'new UiSelector().textContains("{text}")',
        )) > 0
    except Exception:
        return False


def _connect_to_step2(drv, serial: str, wait_ble: int = 60) -> bool:
    """From Step 1, enter serial → Connect → wait for Step 2. Returns True on success."""
    if not drv.is_visible_text(_STEP1_TEXT, timeout=5):
        return False
    try:
        el = drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")
        el.clear()
        el.send_keys(serial)
        time.sleep(0.5)
    except Exception:
        log.info("[connect] No EditText — device already registered, connecting directly")
    try:
        drv.tap_text("Connect", timeout=5, contains=False)
    except Exception:
        log.warning("[connect] Connect button not found — screen may have changed")
        return False

    deadline = time.monotonic() + wait_ble
    while time.monotonic() < deadline:
        if _has_text(drv, _STEP2_TEXT):
            return True
        if _has_text(drv, _STEP3_TEXT):
            log.warning("[connect] Step 2 auto-pass detected (study registered on web) → tapping Step 3 Continue immediately")
            try:
                drv.tap_text("Continue", timeout=5, contains=False)
            except Exception:
                pass
            return False  # Skip Step 2 regression
        if _has_text(drv, _MAIN_TEXT):
            log.warning("[connect] Already measuring")
            return False
        time.sleep(0.5)
    return False


def _proceed_to_start_study(drv) -> bool:
    """Navigate from the current screen to the Start Study screen.

    Since _connect_to_step2 may have already tapped Continue on Step 3,
    wait for the Start Study screen; if still on Step 2/3, tap Continue.
    """
    continued_step2 = False
    continued_step3 = False

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _has_text(drv, _MAIN_TEXT):
            log.info("[proceed] Already measuring")
            return True
        if _has_text(drv, _START_TEXT):
            return True
        if not continued_step3 and _has_text(drv, _STEP3_TEXT):
            log.info("[proceed] Step 3 → Continue")
            try:
                drv.tap_text("Continue", timeout=5, contains=False)
            except Exception:
                pass
            continued_step3 = True
            time.sleep(0.5)
            continue
        if not continued_step2 and _has_text(drv, _STEP2_TEXT):
            log.info("[proceed] Step 2 → Continue")
            try:
                drv.tap_text("Continue", timeout=5, contains=False)
            except Exception:
                pass
            continued_step2 = True
            time.sleep(0.5)
            continue
        time.sleep(0.5)
    return False


def _start_study(drv) -> bool:
    """Tap the Start Study button → wait for the main measurement screen."""
    if not drv.is_visible_text(_START_TEXT, timeout=5):
        return False
    drv.tap_text(_START_TEXT, timeout=5)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if drv.is_visible_text(_MAIN_TEXT, timeout=2):
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# Regression helpers
# ---------------------------------------------------------------------------

def _run_suite(runner, tests, suite_name) -> dict:
    pre = len(runner.results)
    runner.run_all(tests)
    batch = runner.results[pre:]
    passed   = sum(1 for r in batch if r.passed)
    failures = [f"{r.name.split('|')[0].strip()}: {r.message}" for r in batch if not r.passed]
    log.info("[regression] %s: %d/%d passed", suite_name, passed, len(batch))
    return {"passed": passed, "total": len(batch), "failures": failures, "_results": batch}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="S-Patch VM Full Automation Runner")
    ap.add_argument("--config", default="config/spatch-vm.yaml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-regression", action="store_true", help="Skip regression suites, go straight to study + injection")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    run_cfg        = cfg.get("run", {})
    a_cfg          = cfg.get("android", {})
    selectors      = cfg.get("selectors", {}).get("android", {})
    slack_cfg      = cfg.get("slack", {})
    recovery_cfg   = cfg.get("recovery", {})
    catalog        = cfg.get("symptom_catalog", {})
    duration_hours = float(run_cfg.get("duration_hours", 24))
    interval_hours = float(run_cfg.get("symptom_interval_hours", 4))
    start_imm      = bool(run_cfg.get("start_immediately", True))
    jitter_sec     = float(run_cfg.get("jitter_seconds", 0))
    quiet_hours    = run_cfg.get("quiet_hours") or {}
    serial         = a_cfg.get("test_serial_number", "680150")
    webhook        = (os.environ.get("SLACK_WEBHOOK_URL") or
                      slack_cfg.get("webhook_url", "")) if slack_cfg.get("enabled") else ""

    skip_regression = args.skip_regression

    if args.dry_run:
        print(f"\n  === DRY RUN: {run_cfg.get('name', 'run')} ===")
        print(f"  Serial      : {serial}")
        print(f"  Duration    : {duration_hours}h")
        print(f"  Interval    : {interval_hours}h  (~{int(duration_hours/interval_hours)} injections)")
        print(f"  Slack       : {'enabled' if webhook else 'disabled'}")
        print(f"  Flow        : serial → menu → connect → signal → start study → main → diary → menu-study → inject\n")
        return

    run_id  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("output", run_id)
    os.makedirs(out_dir, exist_ok=True)

    artifacts = ArtifactManager(out_dir=out_dir)
    reporter  = RunReporter(out_dir=out_dir, run_name=run_cfg.get("name", "run"))
    drv       = AndroidDriver(a_cfg, selectors, artifacts, reporter)
    reporter.log_event("run_start", {"serial": serial, "duration_hours": duration_hours})
    if webhook:
        from src.slack import slack_run_start
        slack_run_start(webhook, serial, duration_hours, interval_hours)

    _udid = a_cfg.get("udid", "")
    _wifi_addr = _udid if (_udid and ":" in _udid and not _udid.startswith("/")) else None
    keep_awake = KeepAwake()
    keep_awake.start(adb_wifi_addr=_wifi_addr)

    suite_results = {}
    runner = TestRunner(drv, artifacts)

    try:
        # ── 1. App restart ───────────────────────────────────────────
        log.info("=" * 55)
        log.info("STEP 1 — App reset")
        reset_to_step1(drv, hard=True)

        # Detect if study is already active (app restarts directly to main screen).
        # Check multiple texts: "Log Symptoms" may be hidden while BT is reconnecting
        # ("Please wait..." overlay), but "My Study Progress" and "Device Status" are visible.
        already_measuring = (
            drv.is_visible_text(_MAIN_TEXT, timeout=3)
            or drv.is_visible_text("My Study Progress", timeout=3)
            or drv.is_visible_text("Device Status", timeout=3)
        )

        if already_measuring:
            log.info("App already measuring — skipping serial/menu/signal regression and Step 2/3 navigation")
            for s in ("serial", "menu", "signal"):
                suite_results[s] = {"passed": 0, "total": 0, "failures": [], "skipped": True}
                reporter.log_event("regression_suite_result", {"suite": s, "passed": 0, "total": 0, "failures": [], "skipped": True})
            reporter.log_event("study_started", {})
            log.info("Study in progress confirmed")
        else:
            if skip_regression:
                log.info("--skip-regression: skipping serial / menu / signal suites")
                for s in ("serial", "menu", "signal"):
                    suite_results[s] = {"passed": 0, "total": 0, "failures": [], "skipped": True}
                    reporter.log_event("regression_suite_result", {"suite": s, "passed": 0, "total": 0, "failures": [], "skipped": True})
            else:
                # ── 2. Regression: serial + menu ─────────────────────
                log.info("=" * 55)
                log.info("REGRESSION — serial")
                suite_results["serial"] = _run_suite(runner, serial_input.TESTS, "serial")
                reporter.log_event("regression_suite_result", {
                    "suite": "serial", **{k: suite_results["serial"][k] for k in ("passed", "total", "failures")},
                })
                if webhook:
                    r = suite_results["serial"]
                    slack_regression_suite(webhook, "serial", r["passed"], r["total"], r.get("failures", []))

                reset_to_step1(drv, hard=True)
                log.info("=" * 55)
                log.info("REGRESSION — menu")
                suite_results["menu"] = _run_suite(runner, menu_step1.TESTS, "menu")
                reporter.log_event("regression_suite_result", {
                    "suite": "menu", **{k: suite_results["menu"][k] for k in ("passed", "total", "failures")},
                })
                if webhook:
                    r = suite_results["menu"]
                    slack_regression_suite(webhook, "menu", r["passed"], r["total"], r.get("failures", []))

            # ── 3. Connect → Step 2 ──────────────────────────────────
            log.info("=" * 55)
            log.info("STEP 2 — Connecting serial %s", serial)
            reset_to_step1(drv, hard=True)
            on_step2 = _connect_to_step2(drv, serial)

            # ── 4. Regression: signal (on Step 2 screen) ──────────────
            if not skip_regression:
                if on_step2:
                    log.info("=" * 55)
                    log.info("REGRESSION — signal")
                    suite_results["signal"] = _run_suite(runner, signal_check.TESTS, "signal")
                    reporter.log_event("regression_suite_result", {
                        "suite": "signal", **{k: suite_results["signal"][k] for k in ("passed", "total", "failures")},
                    })
                    if webhook:
                        r = suite_results["signal"]
                        slack_regression_suite(webhook, "signal", r["passed"], r["total"], r.get("failures", []))
                else:
                    log.warning("[signal] Failed to enter Step 2 — skipping signal regression")
                    suite_results["signal"] = {"passed": 0, "total": 0, "failures": [], "skipped": True}
                    reporter.log_event("regression_suite_result", {"suite": "signal", "passed": 0, "total": 0, "failures": [], "skipped": True})

            # ── 5. Continue → Step 3 → Start Study ───────────────────
            log.info("=" * 55)
            log.info("STEP 3 — Proceeding to Start Study")
            on_start = _proceed_to_start_study(drv)
            if not on_start:
                raise RuntimeError("Failed to enter Start Study screen — please verify that a study is registered on the web")

            if drv.is_visible_text(_MAIN_TEXT, timeout=2):
                log.info("Already measuring — skipping Start Study")
            else:
                log.info("Tapping Start Study")
                if not _start_study(drv):
                    raise RuntimeError("Study start failed — main screen not displayed after Start Study")

            reporter.log_event("study_started", {})
            log.info("Study started successfully")

            # ── 6. Regression: main + diary + menu-study ─────────────
            if skip_regression:
                log.info("--skip-regression: skipping main / diary / menu-study / connectivity suites")
                for s in ("main", "diary", "menu-study", "connectivity"):
                    suite_results[s] = {"passed": 0, "total": 0, "failures": [], "skipped": True}
                    reporter.log_event("regression_suite_result", {"suite": s, "passed": 0, "total": 0, "failures": [], "skipped": True})
            else:
                log.info("=" * 55)
                log.info("REGRESSION — main")
                suite_results["main"] = _run_suite(runner, main_screen.TESTS, "main")
                reporter.log_event("regression_suite_result", {
                    "suite": "main", **{k: suite_results["main"][k] for k in ("passed", "total", "failures")},
                })
                if webhook:
                    r = suite_results["main"]
                    slack_regression_suite(webhook, "main", r["passed"], r["total"], r.get("failures", []))

                log.info("=" * 55)
                log.info("REGRESSION — diary")
                suite_results["diary"] = _run_suite(runner, add_diary.TESTS, "diary")
                reporter.log_event("regression_suite_result", {
                    "suite": "diary", **{k: suite_results["diary"][k] for k in ("passed", "total", "failures")},
                })
                if webhook:
                    r = suite_results["diary"]
                    slack_regression_suite(webhook, "diary", r["passed"], r["total"], r.get("failures", []))

                log.info("=" * 55)
                log.info("REGRESSION — menu-study")
                suite_results["menu-study"] = _run_suite(runner, menu_study.TESTS, "menu-study")
                reporter.log_event("regression_suite_result", {
                    "suite": "menu-study", **{k: suite_results["menu-study"][k] for k in ("passed", "total", "failures")},
                })
                if webhook:
                    r = suite_results["menu-study"]
                    slack_regression_suite(webhook, "menu-study", r["passed"], r["total"], r.get("failures", []))

                log.info("=" * 55)
                log.info("REGRESSION — connectivity")
                suite_results["connectivity"] = _run_suite(runner, connectivity.TESTS, "connectivity")
                reporter.log_event("regression_suite_result", {
                    "suite": "connectivity", **{k: suite_results["connectivity"][k] for k in ("passed", "total", "failures")},
                })
                if webhook:
                    r = suite_results["connectivity"]
                    slack_regression_suite(webhook, "connectivity", r["passed"], r["total"], r.get("failures", []))

        # ── 7. Connectivity monitoring thread ─────────────────────
        _stop_monitor    = threading.Event()
        _airplane_active = threading.Event()
        _bt_active       = threading.Event()

        def _connectivity_monitor():
            while not _stop_monitor.is_set():
                if not _airplane_active.is_set():
                    try:
                        drv.check_connectivity()
                    except Exception as _e:
                        log.warning("[connectivity monitor] error: %s", _e)
                _stop_monitor.wait(30)  # check every 30 seconds

        monitor_thread = threading.Thread(target=_connectivity_monitor, daemon=True)
        monitor_thread.start()
        log.info("Connectivity monitor started (30s interval, paused during airplane mode)")

        _first_injection_done = threading.Event()

        bt_interval_h  = float(run_cfg.get("bt_disconnect_interval_hours", 0))
        bt_minutes     = float(run_cfg.get("bt_disconnect_minutes", 10))
        ap_interval_h  = float(run_cfg.get("airplane_mode_interval_hours", 0))
        ap_minutes     = float(run_cfg.get("airplane_mode_minutes", 5))

        if bt_interval_h > 0 or ap_interval_h > 0:
            interval_h = bt_interval_h or ap_interval_h
            def _periodic_loop():
                _first_injection_done.wait()
                while not _stop_monitor.is_set():
                    # BT disconnect (injection blocked) → wait 1 min
                    if bt_interval_h > 0:
                        _bt_active.set()
                        try:
                            run_bt_disconnect(drv, bt_minutes)
                        except Exception as _e:
                            log.warning("[bt_disconnect] error: %s", _e)
                        finally:
                            _bt_active.clear()
                        _stop_monitor.wait(60)
                        if _stop_monitor.is_set():
                            break
                    # Airplane mode (connectivity monitor + injection blocked) → wait 1 min
                    if ap_interval_h > 0:
                        _airplane_active.set()
                        try:
                            run_airplane_mode(drv, ap_minutes)
                        except Exception as _e:
                            log.warning("[airplane_mode] error: %s", _e)
                        finally:
                            _airplane_active.clear()
                        _stop_monitor.wait(60)
                        if _stop_monitor.is_set():
                            break
                    # Wait remaining interval
                    _stop_monitor.wait(interval_h * 3600)
            threading.Thread(target=_periodic_loop, daemon=True).start()
            log.info("Periodic loop started (after first injection): BT %.1fmin → 1min → airplane %.1fmin → 1min → wait %.1fh", bt_minutes, ap_minutes, interval_h)

        # ── 8. Symptom injection schedule ────────────────────────
        log.info("=" * 55)
        log.info("INJECTION — starting scheduler (%.1fh, every %.1fh)", duration_hours, interval_hours)
        reporter.log_event("injection_schedule_start", {
            "duration_hours": duration_hours,
            "interval_hours": interval_hours,
        })

        symptoms_pool   = catalog.get("symptoms", SYMPTOMS)   if isinstance(catalog, dict) else SYMPTOMS
        activities_pool = catalog.get("activities", ACTIVITIES) if isinstance(catalog, dict) else ACTIVITIES

        injection_count  = [0]
        injection_result = {"success": False, "symptom": "", "activity": "", "elapsed_sec": 0}

        def job(at_hour=None, payload=None):
            payload   = payload or {}
            symptoms  = payload.get("symptoms") or [random.choice(symptoms_pool)]
            acts      = payload.get("activities") or [random.choice(activities_pool)]
            symptom   = symptoms[0]
            activity  = acts[0]
            # Wait until BT disconnect and airplane mode tests are not running
            if _bt_active.is_set() or _airplane_active.is_set():
                log.info("[job] BT/airplane test in progress — waiting before injection")
                while _bt_active.is_set() or _airplane_active.is_set():
                    time.sleep(5)
            t = time.monotonic()
            try:
                inject_symptom_event(drv, symptoms=symptoms, activities=acts)
                elapsed = round(time.monotonic() - t, 1)
                injection_count[0] += 1
                injection_result.update({
                    "success": True,
                    "symptom": symptom,
                    "activity": activity,
                    "elapsed_sec": elapsed,
                })
                if webhook:
                    slack_injection_notify(
                        webhook, injection_count[0], symptom, activity, elapsed, success=True
                    )
            except Exception as e:
                elapsed = round(time.monotonic() - t, 1)
                injection_count[0] += 1
                injection_result.update({"success": False, "error": str(e)})
                if webhook:
                    slack_injection_notify(
                        webhook, injection_count[0], symptom, activity, elapsed,
                        success=False, error=str(e)
                    )
                raise
            finally:
                _first_injection_done.set()

        scheduler = LongRunScheduler(
            duration_hours=duration_hours,
            interval_hours=interval_hours,
            start_immediately=start_imm,
            plan=cfg.get("symptom_plan") or [],
            catalog=symptoms_pool,
            reporter=reporter,
            jitter_seconds=jitter_sec,
            quiet_hours=quiet_hours,
            recovery_cfg=recovery_cfg,
        )
        scheduler.run(job, driver=drv)
        _stop_monitor.set()

        reporter.log_event("run_complete", {"injection_count": injection_count[0]})
        log.info("Automation complete — total %d injections", injection_count[0])

    except Exception as e:
        reporter.log_event("run_failed", {"error": str(e)})
        log.error("Automation failed: %s", e)
        injection_result = {"success": False, "error": str(e)}
        raise

    finally:
        # ── 8. Slack final report ──────────────────────────────────
        if webhook:
            total_p = sum(v["passed"] for v in suite_results.values() if not v.get("skipped"))
            total_t = sum(v["total"]  for v in suite_results.values() if not v.get("skipped"))
            if total_t > 0 and (total_t - total_p) >= 3:
                slack_urgent_alert(webhook, f"{total_t - total_p} tests failed")
            slack_daily_report(
                webhook, suite_results, injection_result,
                duration_hours=duration_hours,
                interval_hours=interval_hours,
                injection_count=injection_count[0],
            )
            slack_bug_report(webhook)
            log.info("Slack report sent successfully")

        try:
            reporter.render_html_summary()
        except Exception:
            pass

        keep_awake.stop()
        drv.close()


if __name__ == "__main__":
    main()
