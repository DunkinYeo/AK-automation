"""
Standalone entry point: capture AccurKardia's exported app-log zip and pull
it to a local directory. Launched as a subprocess by web/app.py's
/api/capture-logs (mirrors how main.py is launched for a full run), kept
separate from the regression-run config schema since it needs only a
device serial and an output directory.

Usage: python src/capture_logs.py --device <serial|ip:port> --out <dir>
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from src.driver import AndroidDriver
from src.artifacts import ArtifactManager
from src.reporter import RunReporter
from src.log_capture import capture_app_logs, LogCaptureError


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Capture AccurKardia's exported app-log zip via the hidden File Information screen"
    )
    ap.add_argument("--device", required=True, help="Android device serial or ip:port")
    ap.add_argument("--out", required=True, help="Local directory to save the pulled zip into")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    root = Path(__file__).resolve().parent.parent
    cfg = yaml.safe_load((root / "config" / "accurkardia.yaml").read_text(encoding="utf-8"))
    a_cfg = dict(cfg["android"])
    a_cfg["udid"] = args.device
    sel = cfg["selectors"]["android"]

    artifacts = ArtifactManager(str(out_dir))
    reporter = RunReporter(str(out_dir), "capture_logs")

    drv = None
    try:
        drv = AndroidDriver(a_cfg, sel, artifacts, reporter)
        zip_path = capture_app_logs(drv, out_dir)
        print(f"CAPTURE_OK:{zip_path}")
        return 0
    except LogCaptureError as e:
        print(f"CAPTURE_FAIL:{e}")
        return 1
    finally:
        if drv is not None:
            try:
                drv.drv.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
