"""
iOS entry point for AccurKardia long-run automation.

NEW FILE — does not modify src/main.py (Android) in any way.
Differences from main.py:
  - Uses IOSDriver / DeviceManagerIOS instead of AndroidDriver / DeviceManager
  - Uses helpers_ios.go_to_main / reset_to_step1 instead of Android versions
  - No bt_disconnect / airplane_mode (ADB-dependent, not available on iOS)
  - Reads config from ios: section instead of android:
"""
import argparse
import datetime
import logging
import os
import random
import sys
import time

log = logging.getLogger(__name__)

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

from src.reporter import RunReporter
from src.scheduler import LongRunScheduler
from src.artifacts import ArtifactManager
from src.slack import (
    slack_run_start, slack_injection_notify,
    slack_run_complete, slack_run_failed,
)
from src.timeline import log_event
from src.regression.helpers_ios import go_to_main, reset_to_step1
from src.regression.runner import TestRunner
from src.device_manager_ios import DeviceManagerIOS
from src.workflows.symptom_inject import inject_symptom_event, SYMPTOMS
from src.artifact_manager import save_failure_artifacts


def _ensure_xcuitest(reporter: RunReporter) -> None:
    """Preflight: ensure xcuitest Appium driver is installed."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["appium", "driver", "list", "--installed"],
            stderr=subprocess.STDOUT, timeout=30,
        ).decode("utf-8", errors="ignore")
        if "xcuitest" in out.lower():
            return
    except Exception:
        return
    reporter.log_event("appium_driver_install_start", {"driver": "xcuitest"})
    try:
        import subprocess
        subprocess.check_call(["appium", "driver", "install", "xcuitest"], timeout=180)
        reporter.log_event("appium_driver_install_done", {"driver": "xcuitest"})
    except Exception as e:
        reporter.log_event("appium_driver_install_failed", {"driver": "xcuitest", "error": str(e)})


def load_cfg(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    ap = argparse.ArgumentParser(description="S-Patch AccurKardia iOS long-run test automation")
    ap.add_argument("--config", required=True, help="Path to iOS config yaml")
    ap.add_argument("--dry-run", action="store_true", help="Validate config only")
    ap.add_argument("--once", action="store_true", help="Single injection then exit")
    ap.add_argument("--skip-regression", action="store_true",
                    help="Skip regression, go straight to symptom injection")
    args = ap.parse_args()

    cfg            = load_cfg(args.config)
    run_cfg        = cfg.get("run") or {}
    duration_hours = float(run_cfg.get("duration_hours", 24))
    interval_hours = float(run_cfg.get("symptom_interval_hours", 4))
    start_imm      = bool(run_cfg.get("start_immediately", True))
    jitter_seconds = float(run_cfg.get("jitter_seconds", 0))
    quiet_hours    = run_cfg.get("quiet_hours") or {}
    recovery_cfg   = cfg.get("recovery") or {}
    ios_cfg        = cfg.get("ios") or {}
    sel            = (cfg.get("selectors") or {}).get("ios") or {}
    catalog        = cfg.get("symptom_catalog") or {}

    if args.dry_run:
        print(f"\n  === DRY RUN (iOS): {run_cfg.get('name', 'run')} ===")
        print(f"  Device   : {ios_cfg.get('device_name')} ({ios_cfg.get('udid', 'auto')})")
        print(f"  iOS      : {ios_cfg.get('platform_version')}")
        print(f"  Bundle   : {ios_cfg.get('bundle_id')}")
        print(f"  Appium   : {ios_cfg.get('appium_server_url', 'http://127.0.0.1:4723')}")
        print(f"  Duration : {duration_hours}h  interval: {interval_hours}h")
        print(f"  Team ID  : {ios_cfg.get('xcode_org_id', '(not set)')}")
        print("\n  Config OK. Exiting (dry run).\n")
        sys.exit(0)

    run_id    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir   = os.path.join("output", f"ios_{run_id}")
    os.makedirs(out_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(out_dir, "run.log"), encoding="utf-8"),
        ],
    )

    hub_cfg  = cfg.get("hub") or {}
    reporter = RunReporter(
        out_dir=out_dir,
        run_name=run_cfg.get("name", "ios_run"),
        hub_url=hub_cfg.get("url", "") if hub_cfg.get("enabled") else "",
        tester_name=hub_cfg.get("tester_name", ""),
    )
    artifacts = ArtifactManager(out_dir=out_dir)

    slack_cfg = cfg.get("slack") or {}
    _webhook  = os.environ.get("SLACK_WEBHOOK_URL") or slack_cfg.get("webhook_url", "")
    _mention  = slack_cfg.get("mention", "")
    _slack_on = bool(slack_cfg.get("enabled") and _webhook)

    reporter.log_event("run_start_ios", {
        "platform": "ios",
        "duration_hours": duration_hours,
        "interval_hours": interval_hours,
        "bundle_id": ios_cfg.get("bundle_id"),
        "udid": ios_cfg.get("udid"),
    })
    log_event(f"iOS run started: {run_cfg.get('name', 'ios_run')} ({duration_hours}h)")

    dm = None
    try:
        _ensure_xcuitest(reporter)
        dm = DeviceManagerIOS(ios_cfg, sel, artifacts=artifacts, reporter=reporter)
        driver = dm.driver
        reporter.log_event("device_info_ios", driver.get_device_info())

        symptoms_pool = (catalog.get("symptoms", SYMPTOMS)
                         if isinstance(catalog, dict) else SYMPTOMS)

        # ── Single injection mode ────────────────────────────────────────────
        if args.once:
            go_to_main(driver)
            symptom = symptoms_pool[0] if symptoms_pool else None
            inject_symptom_event(driver, symptoms=[symptom] if symptom else None)
            log.info("[once-iOS] Injection complete  symptom=%s", symptom)
            return

        # ── Regression (optional) ────────────────────────────────────────────
        runner = TestRunner(driver, artifacts)

        def _run_suite(name, tests):
            log_event(f"regression (iOS): {name}")
            pre = len(runner.results)
            runner.run_all(tests)
            batch    = runner.results[pre:]
            skipped  = [r for r in batch if r.skipped]
            active   = [r for r in batch if not r.skipped]
            passed   = sum(1 for r in active if r.passed)
            failures = [f"{r.name.split('|')[0].strip()}: {r.message}"
                        for r in active if not r.passed]
            skip_notes = [f"{r.name.split('|')[0].strip()}: {r.message}" for r in skipped]
            reporter.log_event("regression_suite_result_ios", {
                "suite": name, "passed": passed, "total": len(active),
                "failures": failures, "skipped_tests": skip_notes,
            })
            if _slack_on:
                try:
                    from src.slack import slack_regression_suite
                    slack_regression_suite(_webhook, f"[iOS] {name}",
                                           passed, len(active), failures, skip_notes)
                except Exception:
                    pass

        if not args.skip_regression:
            # iOS regression: reuse same test files — they use drv.tap_text()
            # which works identically via IOSDriver
            from src.regression import serial_input, menu_step1, main_screen, add_diary, menu_study

            reset_to_step1(driver, hard=True)
            already_measuring = False
            for _ in range(10):
                if driver.is_visible_text("Log Symptoms", timeout=2):
                    already_measuring = True
                    break
                if driver.is_visible_text("Connect Your S-Patch", timeout=1):
                    break
                time.sleep(1)

            if already_measuring:
                log.info("[iOS] Already measuring — skipping pre-main regression")
            else:
                _run_suite("serial", serial_input.TESTS)
                _run_suite("menu",   menu_step1.TESTS)

            go_to_main(driver)
            _run_suite("main",       main_screen.TESTS)
            _run_suite("diary",      add_diary.TESTS)
            _run_suite("menu-study", menu_study.TESTS)
        else:
            log_event("regression: skipped (--skip-regression)")
            go_to_main(driver)

        reporter.log_event("main_screen_confirmed_ios", {})
        log_event("iOS main screen confirmed")

        # ── Long-run symptom injection loop ──────────────────────────────────
        serial_label = ios_cfg.get("udid", "ios-device")
        if _slack_on:
            slack_run_start(_webhook, serial=serial_label,
                            duration_hours=duration_hours,
                            interval_hours=interval_hours, mention=_mention)

        inject_count = 0

        def job(at_hour=None, payload=None):
            nonlocal inject_count
            inject_count += 1
            payload  = payload or {}
            symptoms = payload.get("symptoms") or []
            if not symptoms:
                symptoms = [random.choice(symptoms_pool)]
            symptom = symptoms[0]
            t0 = time.monotonic()
            try:
                inject_symptom_event(driver, symptoms=symptoms, activities=None)
                elapsed = round(time.monotonic() - t0, 1)
                if _slack_on:
                    slack_injection_notify(_webhook, count=inject_count,
                                           symptom=symptom, elapsed_sec=elapsed,
                                           success=True, mention=_mention)
            except Exception as e:
                if _slack_on:
                    slack_injection_notify(_webhook, count=inject_count,
                                           symptom=symptom, elapsed_sec=0,
                                           success=False, error=str(e), mention=_mention)
                raise

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

        reporter.log_event("run_complete_ios", {"status": "ok"})
        log_event("iOS run complete")
        if _slack_on:
            slack_run_complete(_webhook, run_id=run_id,
                               injection_count=inject_count,
                               duration_hours=duration_hours, mention=_mention)

    except Exception as e:
        reporter.log_event("run_failed_ios", {"error": str(e)})
        log_event(f"iOS run failed: {e}")
        save_failure_artifacts(dm.driver if dm else None, e, label=f"ios_{run_id}")
        if _slack_on:
            slack_run_failed(_webhook, run_id=run_id, error=str(e), mention=_mention)
        raise

    finally:
        if dm:
            dm.close()
        try:
            reporter.render_html_summary()
        except Exception:
            pass


if __name__ == "__main__":
    main()
