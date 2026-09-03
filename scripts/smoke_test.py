"""
Smoke test for the standalone bundle — no device, no Appium needed.

Verifies the environment-level things that have actually broken on tester
machines (import errors, missing timezone data, web app boot). Run with the
bundle's own Python so what's tested is what testers run:

  CI (Windows runner):  automation\\python\\python.exe automation\\scripts\\smoke_test.py
  Tester (smoke.bat):   double-click smoke.bat in the ZIP root
  Dev Mac:              .venv/bin/python scripts/smoke_test.py

Must run with .venv/bin/python (or the bundle's own python) — the plain
`python3` on PATH has none of requirements.txt installed and fails on
[1/6] (Python version) and every import check (issue #19).

Exit code 0 = all checks passed.
"""
import os
import platform
import sys
import traceback
from pathlib import Path

# Make `src.*` / `web.*` importable regardless of cwd (bundle: automation/).
# Frozen-aware (issue #46): under a PyInstaller freeze, __file__ resolves
# inside the ephemeral extraction temp dir, not the real install
# directory -- os.chdir() into that would break every relative path
# elsewhere (config writes, output/ creation) for the rest of the process.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.app_root import get_app_root

ROOT = get_app_root()
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


@check("Dashboard page (\"/\") renders its template")
def _dashboard_page():
    # Added for issue #46 (ported from a real bug MA hit): a frozen build
    # can ship with web/templates/ missing entirely from the distribution
    # if the build script doesn't copy it as a loose file. /api/init above
    # doesn't touch render_template() at all, so this gap can ship past
    # every other check. Catch it here instead.
    from web.app import app
    resp = app.test_client().get("/")
    assert resp.status_code == 200, f"\"/\" returned {resp.status_code}"
    assert b"Accurkardia" in resp.data, "\"/\" response doesn't look like the dashboard page"


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
