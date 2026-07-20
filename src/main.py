import argparse
import datetime
import logging
import os
import random
import subprocess
import sys
import threading
import time

log = logging.getLogger(__name__)

# Allow running as `python src/main.py` from project root
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

import yaml

from src.device_manager import DeviceManager
from src.reporter import RunReporter
from src.scheduler import LongRunScheduler
from src.artifacts import ArtifactManager
from src.slack import (
    slack_run_start, slack_injection_notify,
    slack_run_complete, slack_run_failed, slack_notify,
)
from src.timeline import log_event
from src.regression.helpers import go_to_main
from src.regression.runner import TestRunner
from src.regression import serial_input, menu_step1, main_screen, add_diary, menu_study, connectivity
from src.regression.helpers import reset_to_step1
from src.workflows.symptom_inject import inject_symptom_event, SYMPTOMS, ACTIVITIES
from src.workflows.bt_disconnect import run_bt_disconnect
from src.workflows.airplane_mode import run_airplane_mode
from src.artifact_manager import save_failure_artifacts
from src.keep_awake import KeepAwake


def ensure_uiautomator2(reporter: RunReporter) -> None:
    """Preflight: ensure the uiautomator2 Appium driver is installed.

    On Windows, npm global scripts are .cmd files so we call appium.cmd.
    Best-effort — if the check itself fails we skip and let Appium error
    naturally during driver connection.
    """
    appium = "appium.cmd" if sys.platform == "win32" else "appium"
    try:
        out = subprocess.check_output(
            [appium, "driver", "list", "--installed"],
            stderr=subprocess.STDOUT,
            timeout=30,
        ).decode("utf-8", errors="ignore")
        if "uiautomator2" in out.lower():
            return  # already installed
    except Exception:
        return  # appium not reachable — skip preflight

    reporter.log_event("appium_driver_install_start", {"driver": "uiautomator2"})
    try:
        subprocess.check_call([appium, "driver", "install", "uiautomator2"], timeout=180)
        reporter.log_event("appium_driver_install_done", {"driver": "uiautomator2"})
    except Exception as e:
        reporter.log_event("appium_driver_install_failed", {"driver": "uiautomator2", "error": str(e)})


def load_cfg(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Screen-timeout original value, persisted so the web backstop can restore
# the EXACT tester setting even if this process is hard-killed (review
# 2026-07-14). Single source of truth for all three defense layers.
_SCREEN_ORIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runtime", "screen_timeout_orig.json")


def _save_screen_orig(val: str) -> None:
    try:
        import json
        os.makedirs(os.path.dirname(_SCREEN_ORIG_FILE), exist_ok=True)
        with open(_SCREEN_ORIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"orig": val, "saved_at": datetime.datetime.now().isoformat()}, f)
    except Exception:
        pass


def _read_screen_orig() -> str | None:
    try:
        import json
        with open(_SCREEN_ORIG_FILE, encoding="utf-8") as f:
            v = str(json.load(f).get("orig", ""))
        return v if v.isdigit() else None
    except Exception:
        return None


def _clear_screen_orig() -> None:
    try:
        os.remove(_SCREEN_ORIG_FILE)
    except Exception:
        pass


def _dry_run(cfg: dict) -> None:
    """Validate config and print what will run — no device connection."""
    run_cfg    = cfg.get("run") or {}
    a_cfg      = cfg.get("android") or {}
    catalog    = cfg.get("symptom_catalog") or []
    plan       = cfg.get("symptom_plan") or []
    platform   = (cfg.get("platform") or "android").lower()
    quiet_hrs  = run_cfg.get("quiet_hours") or {}
    jitter     = float(run_cfg.get("jitter_seconds", 0))
    duration_h = int(run_cfg.get("duration_hours", 24))
    interval_h = float(run_cfg.get("symptom_interval_hours", 4))
    rec_cfg    = cfg.get("recovery") or {}

    errors = []
    if platform != "android":
        errors.append(f"Unsupported platform: {platform!r} (only 'android' supported)")
    if not a_cfg.get("app_package"):
        errors.append("android.app_package is required")
    if not a_cfg.get("app_activity"):
        errors.append("android.app_activity is required")

    if errors:
        print("\n  [DRY RUN] Config errors found:")
        for e in errors:
            print(f"    ✗ {e}")
        sys.exit(1)

    print(f"\n  === DRY RUN: {run_cfg.get('name', 'run')} ===")
    print(f"  Platform : {platform}")
    print(f"  Device   : udid={a_cfg.get('udid') or '(auto)'}")
    print(f"  App      : {a_cfg.get('app_package')} / {a_cfg.get('app_activity')}")
    print(f"  Appium   : {a_cfg.get('appium_server_url', 'http://127.0.0.1:4723')}")
    print(f"  Duration : {duration_h}h")

    if quiet_hrs:
        print(f"  Quiet    : {quiet_hrs.get('start')}:00 – {quiet_hrs.get('end')}:00 (jobs skipped)")

    if rec_cfg:
        print(f"  Recovery : cooldown={rec_cfg.get('cooldown_seconds_between_steps', 30)}s  "
              f"max_retries={rec_cfg.get('max_retries_per_job', 3)}")

    if plan:
        now = datetime.datetime.now()
        print(f"\n  Scheduled plan ({len(plan)} events):")
        for item in plan:
            at = float(item.get("at_hour", 0))
            jstr = f" ±{jitter}s" if jitter else ""
            when = now + datetime.timedelta(hours=at)
            print(
                f"    +{at:5.1f}h ({when.strftime('%H:%M')}){jstr}"
                f"  symptoms={item.get('symptoms')}  other='{item.get('other_text', '')}'"
            )
    else:
        n = int(duration_h / interval_h)
        jstr = f" ±{jitter}s jitter" if jitter else ""
        print(f"\n  Interval mode: every {interval_h}h{jstr}  →  ~{n} injections")
        print(f"  Catalog ({len(catalog)} items): {catalog}")

    print("\n  Config OK. Exiting (dry run).\n")
    sys.exit(0)


def _run_once(cfg: dict, reporter: RunReporter, artifacts: ArtifactManager) -> None:
    """Connect to device, inject one symptom, then exit — for quick verification."""
    platform = (cfg.get("platform") or "android").lower()
    if platform != "android":
        raise RuntimeError("Only android is supported. Set platform: android")

    a_cfg   = cfg.get("android") or {}
    sel     = (cfg.get("selectors") or {}).get("android") or {}
    catalog = cfg.get("symptom_catalog") or []
    plan    = cfg.get("symptom_plan") or []

    ensure_uiautomator2(reporter)
    dm = DeviceManager(a_cfg, sel, artifacts=artifacts, reporter=reporter)
    driver = dm.driver
    try:
        reporter.log_event("device_info", driver.get_device_info())
        go_to_main(driver)

        if plan and plan[0].get("symptoms"):
            symptoms   = plan[0]["symptoms"]
            activities = plan[0].get("activities") or []
        elif catalog:
            symptoms_catalog   = catalog.get("symptoms", SYMPTOMS)
            activities_catalog = catalog.get("activities", ACTIVITIES)
            symptoms   = [symptoms_catalog[0]]
            activities = [activities_catalog[0]]
        else:
            symptoms, activities = [], []

        reporter.log_event("once_inject_start", {"symptoms": symptoms})
        inject_symptom_event(driver, symptoms=symptoms or None, activities=activities or None)
        reporter.log_event("once_inject_done", {"symptoms": symptoms, "status": "ok"})
        print(f"\n  --once: injection complete  symptoms={symptoms}\n")
    finally:
        dm.close()


def main():
    ap = argparse.ArgumentParser(description="S-Patch Accurkardia long-run test automation")
    ap.add_argument("--config", required=True, help="Path to run.yaml")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config and print schedule; no device connection",
    )
    ap.add_argument(
        "--once",
        action="store_true",
        help="Run a single symptom injection for quick verification, then exit",
    )
    ap.add_argument(
        "--skip-regression",
        action="store_true",
        help="Skip regression suites and go straight to symptom injection",
    )
    args = ap.parse_args()

    cfg            = load_cfg(args.config)
    platform       = (cfg.get("platform") or "android").lower()
    run_cfg        = cfg.get("run") or {}
    duration_hours = float(run_cfg.get("duration_hours", 24))
    interval_hours = float(run_cfg.get("symptom_interval_hours", 4))
    start_imm      = bool(run_cfg.get("start_immediately", True))
    jitter_seconds = float(run_cfg.get("jitter_seconds", 0))
    quiet_hours    = run_cfg.get("quiet_hours") or {}
    recovery_cfg   = cfg.get("recovery") or {}
    bt_interval_h  = float(run_cfg.get("bt_disconnect_interval_hours", 0))
    bt_minutes     = float(run_cfg.get("bt_disconnect_minutes", 10))
    ap_interval_h  = float(run_cfg.get("airplane_mode_interval_hours", 0))
    ap_minutes     = float(run_cfg.get("airplane_mode_minutes", 5))

    # Dry run exits before creating output dir or reporter events
    if args.dry_run:
        _dry_run(cfg)

    run_id  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("output", run_id)
    os.makedirs(out_dir, exist_ok=True)

    hub_cfg  = cfg.get("hub") or {}
    reporter = RunReporter(
        out_dir=out_dir,
        run_name=run_cfg.get("name", "run"),
        hub_url=hub_cfg.get("url", "") if hub_cfg.get("enabled") else "",
        tester_name=hub_cfg.get("tester_name", ""),
    )
    artifacts = ArtifactManager(out_dir=out_dir)

    slack_cfg = cfg.get("slack") or {}
    _webhook  = os.environ.get("SLACK_WEBHOOK_URL") or slack_cfg.get("webhook_url", "")
    _mention  = slack_cfg.get("mention", "")
    _slack_on = bool(slack_cfg.get("enabled") and _webhook)

    reporter.log_event(
        "run_start",
        {
            "platform": platform,
            "duration_hours": duration_hours,
            "interval_hours": interval_hours,
            "jitter_seconds": jitter_seconds,
            "quiet_hours": quiet_hours,
            "once": args.once,
        },
    )
    log_event(f"run started: {run_cfg.get('name', 'run')} ({duration_hours}h)")

    # ── Single injection mode ────────────────────────────────────────────────
    if args.once:
        try:
            _run_once(cfg, reporter, artifacts)
        except Exception as e:
            reporter.log_event("run_failed", {"error": str(e)})
            raise
        finally:
            try:
                reporter.render_html_summary()
            except Exception:
                pass
        return

    # ── Full long-run mode ───────────────────────────────────────────────────
    dm = None
    keep_awake = KeepAwake()
    _screen_restore: dict = {}  # filled once the driver sets the run timeout

    # Web Stop sends SIGTERM, which by default kills the process WITHOUT
    # running finally — the screen-timeout restore (and driver cleanup)
    # would be skipped. Convert to SystemExit so finally executes; the web
    # side still SIGKILLs after 5s if cleanup hangs, so worst case is
    # today's behavior.
    import signal as _signal
    _signal.signal(_signal.SIGTERM, lambda *_: sys.exit(143))

    try:
        if platform != "android":
            raise RuntimeError(
                "Only android is implemented in MVP. Set platform: android"
            )

        a_cfg   = cfg.get("android") or {}
        sel     = (cfg.get("selectors") or {}).get("android") or {}
        catalog = cfg.get("symptom_catalog") or []

        wifi_addr = a_cfg.get("udid", "")
        keep_awake.start(adb_wifi_addr=wifi_addr if ":" in wifi_addr else None)

        ensure_uiautomator2(reporter)
        dm = DeviceManager(a_cfg, sel, artifacts=artifacts, reporter=reporter)
        driver = dm.driver
        # Study-completed Slack heads-up is sent from the driver, which has
        # no config access — hand it the webhook (issue #13)
        driver._slack_webhook = _webhook if _slack_on else ""
        reporter.log_event("device_info", driver.get_device_info())

        # ── Regression suites ─────────────────────────────────────────────────
        # Phase 1: Step 1 suites (serial + menu) — no BLE needed
        # Phase 2: go_to_main → main/diary/menu-study/connectivity
        pre_main_suites  = [("serial", serial_input.TESTS), ("menu", menu_step1.TESTS)]
        post_main_suites = [("main", main_screen.TESTS), ("diary", add_diary.TESTS),
                            ("menu-study", menu_study.TESTS), ("connectivity", connectivity.TESTS)]

        runner = TestRunner(driver, artifacts)

        def _check_bt_not_restored(phase: str):
            """Check BT state via ADB after a workflow; alert if BT is still off."""
            import subprocess as _sp
            udid = cfg.get("android", {}).get("udid", "")
            adb = ["adb"] + (["-s", udid] if udid else [])
            try:
                r = _sp.run(adb + ["shell", "settings", "get", "global", "bluetooth_on"],
                            capture_output=True, text=True, timeout=10)
                bt_off = r.stdout.strip() == "0"
                if bt_off:
                    msg = (f"⚠️ *[ACTION REQUIRED]* BT was not restored after {phase}.\n"
                           "  • Tester must manually re-enable Bluetooth on the device.\n"
                           "  • ADB BT enable is not effective on this device/OS.")
                    log.warning("[bt_restore] BT still OFF after %s", phase)
                    reporter.log_event("bt_not_restored", {"phase": phase})
                    if _slack_on:
                        from src.slack import slack_notify
                        slack_notify(_webhook, msg)
            except Exception as _e:
                log.warning("[bt_restore] check failed: %s", _e)

        def _run_suite(name, tests):
            log_event(f"regression: {name}")
            pre = len(runner.results)
            runner.run_all(tests)
            batch    = runner.results[pre:]
            skipped  = [r for r in batch if r.skipped]
            active   = [r for r in batch if not r.skipped]
            passed   = sum(1 for r in active if r.passed)
            failures = [f"{r.name.split('|')[0].strip()}: {r.message}" for r in active if not r.passed]
            skip_notes = [f"{r.name.split('|')[0].strip()}: {r.message}" for r in skipped]
            # Evidence screenshots for failed TCs — report shows the filename
            # so the tester/QA can open it without digging (issue #13)
            failure_shots = {r.name.split("|")[0].strip(): os.path.basename(r.screenshot)
                             for r in active if not r.passed and r.screenshot}
            reporter.log_event("regression_suite_result", {
                "suite": name, "passed": passed, "total": len(active), "failures": failures,
                "skipped_tests": skip_notes,
                "failure_screenshots": failure_shots,
            })
            if _slack_on:
                try:
                    from src.slack import slack_regression_suite
                    slack_regression_suite(_webhook, name, passed, len(active), failures, skip_notes)
                except Exception:
                    pass

        if args.skip_regression:
            # Skip ALL regression suites, connectivity included — the long-run
            # phase exercises injection/BT/airplane anyway (user decision
            # 2026-07-10; previously connectivity still ran here)
            log_event("regression: skipped (--skip-regression)")
            for suite_name, _ in pre_main_suites:
                reporter.log_event("regression_suite_result", {
                    "suite": suite_name, "passed": 0, "total": 0, "failures": [], "skipped": True,
                })
            for suite_name, tests in post_main_suites:
                reporter.log_event("regression_suite_result", {
                    "suite": suite_name, "passed": 0, "total": 0, "failures": [], "skipped": True,
                })
            go_to_main(driver)
        else:
            # Phase 1: Step 1 — reset app, run serial + menu
            reset_to_step1(driver, hard=True)

            # If the study is already active, the app restarts to the main screen
            # (not Step 1). BLE reconnection can take up to 30s — poll until we
            # know whether the app settled on Step 1 or the main screen.
            already_measuring = False
            for _ in range(10):  # up to 30s (10 × 3s)
                if driver.is_visible_text("Log Symptoms", timeout=2):
                    already_measuring = True
                    break
                if driver.is_visible_text("Connect Your S-Patch", timeout=1):
                    break  # confirmed Step 1, no need to wait longer
                time.sleep(1)

            if already_measuring:
                log.info("App already measuring — skipping serial/menu regression")
                for suite_name, _ in pre_main_suites:
                    reporter.log_event("regression_suite_result", {
                        "suite": suite_name, "passed": 0, "total": 0, "failures": [], "skipped": True,
                    })
            else:
                for name, tests in pre_main_suites:
                    _run_suite(name, tests)

            # Phase 2: navigate to main screen, run remaining suites
            # Always call go_to_main — it returns early if already on main screen
            # (checking only "Log Symptoms"; "My Study Progress" also appears on
            #  the disconnected Start Study screen so cannot be used as a guard)
            go_to_main(driver)
            for name, tests in post_main_suites:
                _run_suite(name, tests)

        reporter.log_event("main_screen_confirmed", {})
        log_event("main screen confirmed")

        log_event("starting scheduler")
        serial = a_cfg.get("test_serial_number", a_cfg.get("udid", ""))
        if _slack_on:
            slack_run_start(_webhook, serial=serial, duration_hours=duration_hours,
                            interval_hours=interval_hours, mention=_mention)

        symptoms_pool = catalog.get("symptoms", SYMPTOMS) if isinstance(catalog, dict) else SYMPTOMS

        _first_injection_done = threading.Event()
        _bt_active            = threading.Event()
        _airplane_active      = threading.Event()
        _stop_loop            = threading.Event()
        _inject_active        = threading.Event()
        _stop_monitor         = threading.Event()

        if bt_interval_h > 0 or ap_interval_h > 0:
            _loop_interval_h = bt_interval_h or ap_interval_h
            def _periodic_loop():
                _first_injection_done.wait()
                while not _stop_loop.is_set():
                    if bt_interval_h > 0:
                        _bt_active.set()
                        try:
                            run_bt_disconnect(driver, bt_minutes)
                        except Exception as _e:
                            log.warning("[bt_disconnect] error: %s", _e)
                        finally:
                            _bt_active.clear()
                        _check_bt_not_restored("BT disconnect cycle")
                        _stop_loop.wait(60)
                        if _stop_loop.is_set():
                            break
                    if ap_interval_h > 0:
                        _airplane_active.set()
                        try:
                            run_airplane_mode(driver, ap_minutes)
                        except Exception as _e:
                            log.warning("[airplane_mode] error: %s", _e)
                        finally:
                            _airplane_active.clear()
                        _check_bt_not_restored("airplane mode")
                        _stop_loop.wait(60)
                        if _stop_loop.is_set():
                            break
                    _stop_loop.wait(_loop_interval_h * 3600)
            threading.Thread(target=_periodic_loop, daemon=True).start()
            log.info("Periodic loop started (after first injection): BT %.1fmin → airplane %.1fmin → wait %.1fh",
                     bt_minutes, ap_minutes, _loop_interval_h)

        # Connectivity monitor — detects NATURAL BT drops between jobs.
        # Ported from run.py: main.py long runs had no 30s monitor, so an
        # unscheduled disconnection stayed invisible (and the dashboard BT
        # card stale) until the next hourly job. Paused during airplane
        # tests and injections; intentionally NOT paused during the BT-off
        # window (the bt-off diary check relies on detection there).
        driver._job_busy = threading.Event()  # set by scheduler around each job

        def _connectivity_monitor():
            # Session lifecycle rules (2026-07-10, session-thrash incident +
            # code review):
            #  - This thread NEVER touches the session (no ensure_session/
            #    reconnect) — recovery is owned by the scheduler job path.
            #  - App-crash watch (pure ADB) runs on EVERY tick — crashes are
            #    most likely during injections, so it must not pause; only
            #    the relaunch action is gated while something owns the device.
            #  - check_connectivity DOES touch the UI (popup dismiss, BT-off
            #    diary, ECG check), so it runs only when fully idle — incl.
            #    BT windows, where run_bt_disconnect calls it itself
            #    (double-running raced _conn_state → duplicate diaries).
            while not _stop_monitor.is_set():
                device_owned = (_airplane_active.is_set() or _bt_active.is_set()
                                or _inject_active.is_set() or driver._job_busy.is_set())
                try:
                    driver.ensure_screen_on()  # ADB-only; Pixel pauses charging → stay_awake lapses
                except Exception as _e:
                    log.warning("[screen-watch] error: %s", _e)
                try:
                    driver.check_app_process(allow_relaunch=not device_owned)
                except Exception as _e:
                    log.warning("[app-watch] error: %s", _e)
                if not device_owned:
                    try:
                        driver.check_connectivity()
                    except Exception as _e:
                        # Session/instrumentation died between jobs (e.g. after
                        # an airplane cycle). Without self-heal the monitor is
                        # blind until the next hourly job (observed 15:32→16:14
                        # gap, 2026-07-10). Heal ONLY while idle; reconnect()
                        # itself is lock-serialized against job recovery, so
                        # this can no longer thrash like the 15:07 incident.
                        log.warning("[connectivity monitor] tick failed: %s — recovering session (idle)", _e)
                        try:
                            if not driver._job_busy.is_set():
                                driver.reconnect()
                                driver.check_connectivity()
                        except Exception as _e2:
                            log.warning("[connectivity monitor] recovery failed: %s", _e2)
                _stop_monitor.wait(30)

        threading.Thread(target=_connectivity_monitor, daemon=True,
                         name="conn-monitor").start()
        log.info("Connectivity monitor started (30s interval; paused during airplane/injection)")

        # Charging-independent screen keep-awake: stay_awake capability lapses
        # when the device pauses charging (Pixel battery protection) — the
        # 2026-07-11 soak lost 39h of injections to a locked screen.
        # Restored in the finally block (review 2026-07-14: crash/stop paths
        # must not leave the tester's device polluted).
        _orig = driver.set_screen_timeout(86400000)  # 24h
        # Sanity: if a previous run died without restoring (SIGKILL), the
        # captured "original" may be our marker. Only treat it as pollution
        # when the runtime evidence exists; otherwise respect a tester's
        # intentional 24h screen timeout.
        if _orig == "86400000":
            _orig = _read_screen_orig() or _orig
        _save_screen_orig(_orig)  # lets the web backstop restore the EXACT value
        _screen_restore["driver"] = driver
        _screen_restore["orig"] = _orig
        driver.ensure_screen_on()

        inject_count = 0

        def job(at_hour: float | None = None, payload: dict | None = None):
            nonlocal inject_count
            inject_count += 1
            if _bt_active.is_set() or _airplane_active.is_set():
                log.info("[job] BT/airplane test in progress — waiting before injection")
                while _bt_active.is_set() or _airplane_active.is_set():
                    time.sleep(5)
            payload  = payload or {}
            symptoms = payload.get("symptoms") or []
            if not symptoms:
                symptoms = [random.choice(symptoms_pool)]
            symptom = symptoms[0]
            t0 = time.monotonic()
            _inject_active.set()
            try:
                inject_symptom_event(driver, symptoms=symptoms, activities=None)
                elapsed = round(time.monotonic() - t0, 1)
                if _slack_on:
                    slack_injection_notify(_webhook, count=inject_count, symptom=symptom,
                                           elapsed_sec=elapsed, success=True, mention=_mention)
                # Study nearing completion (issue #10) — one-time Slack heads-up
                warn_pct = getattr(driver, "_study_warn_pending", None)
                if warn_pct is not None:
                    driver._study_warn_pending = None
                    if _slack_on:
                        slack_notify(_webhook,
                                     f"⚠️ App study is at {warn_pct}% — it will finish "
                                     f"before this automation run ends; injections after "
                                     f"study completion will fail. Consider stopping early.",
                                     mention=_mention)
            except Exception as e:
                if _slack_on:
                    slack_injection_notify(_webhook, count=inject_count, symptom=symptom,
                                           elapsed_sec=0, success=False, error=str(e),
                                           mention=_mention)
                raise
            finally:
                _inject_active.clear()
                _first_injection_done.set()

        scheduler = LongRunScheduler(
            duration_hours=duration_hours,
            interval_hours=interval_hours,
            start_immediately=start_imm,
            plan=cfg.get("symptom_plan") or [],
            catalog=catalog,
            reporter=reporter,
            jitter_seconds=jitter_seconds,
            quiet_hours=quiet_hours,
            recovery_cfg=recovery_cfg,
        )
        scheduler.run(job, driver=driver)
        _stop_loop.set()
        _stop_monitor.set()

        reporter.log_event("run_complete", {"status": "ok"})
        log_event("run complete")
        if _slack_on:
            slack_run_complete(_webhook, run_id=run_id, injection_count=inject_count,
                               duration_hours=duration_hours, mention=_mention,
                               failed_jobs=reporter.count_events("job_failed"))

    except Exception as e:
        reporter.log_event("run_failed", {"error": str(e)})
        log_event(f"run failed: {e}")
        save_failure_artifacts(dm.driver if dm else None, e, label=run_id)
        if _slack_on:
            slack_run_failed(_webhook, run_id=run_id, error=str(e), mention=_mention)
        raise

    finally:
        keep_awake.stop()
        # Restore the tester's screen timeout on EVERY exit path — normal
        # completion, exception, Ctrl-C, and web Stop (SIGTERM → SystemExit
        # via the handler installed in main()).
        try:
            if _screen_restore.get("driver") and str(_screen_restore.get("orig", "")).isdigit():
                _drv, _val = _screen_restore["driver"], str(_screen_restore["orig"])
                _drv.set_screen_timeout(int(_val))
                # Verify before deleting the backstop file: a silently failed
                # adb put must leave the file so the web backstop can still
                # restore the exact value (review 2026-07-14 #7)
                if _drv.get_screen_timeout() == _val:
                    _clear_screen_orig()
        except Exception:
            pass
        if dm:
            dm.close()
        try:
            reporter.render_html_summary()
        except Exception:
            pass


if __name__ == "__main__":
    main()
