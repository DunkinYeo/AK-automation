import argparse
import datetime
import os
import random
import subprocess
import sys
import time

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
    slack_run_complete, slack_run_failed,
)
from src.timeline import log_event
from src.workflows.measurement_start import ensure_on_main_screen
from src.workflows.symptom_inject import inject_symptom_event, SYMPTOMS
from src.artifact_manager import save_failure_artifacts


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
        ensure_on_main_screen(driver)

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
    try:
        if platform != "android":
            raise RuntimeError(
                "Only android is implemented in MVP. Set platform: android"
            )

        a_cfg   = cfg.get("android") or {}
        sel     = (cfg.get("selectors") or {}).get("android") or {}
        catalog = cfg.get("symptom_catalog") or []

        ensure_uiautomator2(reporter)
        dm = DeviceManager(a_cfg, sel, artifacts=artifacts, reporter=reporter)
        driver = dm.driver
        reporter.log_event("device_info", driver.get_device_info())

        ensure_on_main_screen(driver)
        reporter.log_event("main_screen_confirmed", {})
        log_event("main screen confirmed — starting scheduler")

        serial = a_cfg.get("test_serial_number", a_cfg.get("udid", ""))
        if _slack_on:
            slack_run_start(_webhook, serial=serial, duration_hours=duration_hours,
                            interval_hours=interval_hours, mention=_mention)

        symptoms_pool = catalog.get("symptoms", SYMPTOMS) if isinstance(catalog, dict) else SYMPTOMS

        inject_count = 0

        def job(at_hour: float | None = None, payload: dict | None = None):
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
                    slack_injection_notify(_webhook, count=inject_count, symptom=symptom,
                                           elapsed_sec=elapsed, success=True, mention=_mention)
            except Exception as e:
                if _slack_on:
                    slack_injection_notify(_webhook, count=inject_count, symptom=symptom,
                                           elapsed_sec=0, success=False, error=str(e),
                                           mention=_mention)
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

        reporter.log_event("run_complete", {"status": "ok"})
        log_event("run complete")
        if _slack_on:
            slack_run_complete(_webhook, run_id=run_id, injection_count=inject_count,
                               duration_hours=duration_hours, mention=_mention)

    except Exception as e:
        reporter.log_event("run_failed", {"error": str(e)})
        log_event(f"run failed: {e}")
        save_failure_artifacts(dm.driver if dm else None, e, label=run_id)
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
