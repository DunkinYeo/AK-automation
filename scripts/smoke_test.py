"""
Smoke test for the standalone bundle — no device, no Appium needed.

Verifies the environment-level things that have actually broken on tester
machines (import errors, missing timezone data, web app boot). Run with the
bundle's own Python so what's tested is what testers run:

  CI (Windows runner):  automation\\python\\python.exe automation\\scripts\\smoke_test.py
  Tester (smoke.bat):   double-click smoke.bat in the ZIP root
  Dev Mac:              python3 scripts/smoke_test.py

Exit code 0 = all checks passed.
"""
import os
import platform
import sys
import traceback
from pathlib import Path

# Make `src.*` / `web.*` importable regardless of cwd (bundle: automation/)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Mirror run.bat/run.command: bundled adb on PATH if present
_adb = ROOT / "runtime" / "platform-tools"
if _adb.is_dir():
    os.environ["PATH"] = str(_adb) + os.pathsep + os.environ.get("PATH", "")

RESULTS = []


def check(name):
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


@check("Python runtime")
def _python():
    print(f"    {platform.python_version()} on {platform.system()} {platform.machine()}")
    assert sys.version_info >= (3, 11), "Python 3.11+ required"


@check("Timezone database (tester-reported crash: America/Chicago)")
def _tzdata():
    import zoneinfo
    zoneinfo.ZoneInfo("America/Chicago")  # exact key from the v1.0.6 crash report


@check("Android entrypoint imports (src.main)")
def _main_android():
    import src.main  # noqa: F401 — pulls appium client, workflows, reporter


@check("iOS entrypoint imports (src.main_ios)")
def _main_ios():
    import src.main_ios  # noqa: F401


@check("Scheduler starts (timezone lookup + UTC fallback)")
def _scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from src.scheduler import _make_scheduler
    sched = _make_scheduler(BackgroundScheduler)
    print(f"    timezone: {sched.timezone}")


@check("Web app boots and /api/init responds")
def _web():
    from web.app import app
    resp = app.test_client().get("/api/init")
    assert resp.status_code == 200, f"/api/init returned {resp.status_code}"
    data = resp.get_json()
    assert "devices" in data, f"unexpected /api/init payload: {data}"
    print(f"    devices={data['devices']} appium={data.get('appium')}")


def main() -> int:
    failed = 0
    total = len(RESULTS)
    for i, (name, fn) in enumerate(RESULTS, 1):
        print(f"[{i}/{total}] {name}")
        try:
            fn()
            print("      PASS")
        except Exception:
            failed += 1
            print("      FAIL")
            traceback.print_exc()
    print()
    if failed:
        print(f"SMOKE FAIL — {failed}/{total} checks failed")
        return 1
    print(f"SMOKE OK — {total}/{total} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
