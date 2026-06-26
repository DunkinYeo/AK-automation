#!/usr/bin/env python3
"""
S-Patch Accurkardia Regression Test Runner

Usage:
    # no device connection needed
    python src/run_regression.py --suite serial
    python src/run_regression.py --suite menu

    # BLE connected, no study registered
    python src/run_regression.py --suite signal
    python src/run_regression.py --suite study

    # study active required
    python src/run_regression.py --suite main
    python src/run_regression.py --suite diary
    python src/run_regression.py --suite menu-study
    python src/run_regression.py --suite connectivity
"""
import argparse
import logging
import os
import sys

import yaml

from src.artifacts import ArtifactManager
from src.reporter import RunReporter
from src.driver import AndroidDriver
from src.regression.runner import TestRunner
from src.regression import serial_input, menu_step1, signal_check, study_popup, main_screen, add_diary, menu_study, connectivity
from src.regression.helpers import reset_to_step1, go_to_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# (tests, setup)
# setup="hard"  : force-restart app → Step 1
# setup="soft"  : back button → Step 1 (BLE retained)
# setup="main"  : Step 1 → Connect → Step 3 → measurement main screen (BLE + study required)
SUITES = {
    "serial":       (serial_input.TESTS,  "hard"),  # Step 1, no BLE
    "menu":         (menu_step1.TESTS,    "hard"),  # Step 1 gear icon, no BLE
    "signal":       (signal_check.TESTS,  "soft"),  # Step 2, BLE connected
    "study":        (study_popup.TESTS,   "soft"),  # Step 2/3, BLE connected
    "main":         (main_screen.TESTS,   "none"),  # run from current screen (study must be active)
    "diary":        (add_diary.TESTS,     "none"),  # run from current screen (study must be active)
    "menu-study":   (menu_study.TESTS,    "none"),  # run from current screen (study must be active)
    "connectivity": (connectivity.TESTS,  "none"),  # run from current screen (study must be active)
}


def main():
    parser = argparse.ArgumentParser(description="S-Patch Accurkardia Regression Test Runner")
    parser.add_argument("--config", default="config/accurkardia.yaml")
    parser.add_argument(
        "--suite",
        default="all",
        help="suite(s) to run: single name, comma-separated list, or 'all'",
    )
    parser.add_argument(
        "--result-json",
        default="",
        help="Path to save results as a JSON file (optional)",
    )
    args = parser.parse_args()

    # Parse suite list (comma-separated or 'all')
    if args.suite == "all":
        suite_list = list(SUITES.items())
    else:
        names = [s.strip() for s in args.suite.split(",") if s.strip()]
        invalid = [n for n in names if n not in SUITES]
        if invalid:
            parser.error(f"Unknown suites: {invalid}. Valid: {list(SUITES.keys())}")
        suite_list = [(n, SUITES[n]) for n in names]

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    a_cfg = cfg.get("android", {})
    selectors = cfg.get("selectors", {}).get("android", {})

    out_dir = "output/regression"
    os.makedirs(out_dir, exist_ok=True)

    artifacts = ArtifactManager(out_dir=out_dir)
    reporter = RunReporter(out_dir=out_dir, run_name="regression")
    drv = AndroidDriver(a_cfg, selectors, artifacts, reporter)

    try:
        runner = TestRunner(drv, artifacts)

        for suite_name, (tests, setup) in suite_list:
            logging.info("=" * 50)
            logging.info("Suite: %s (%d tests)", suite_name, len(tests))
            logging.info("=" * 50)
            if setup == "none":
                pass
            elif setup == "main":
                reset_to_step1(drv, hard=True)
                go_to_main(drv)
            else:
                reset_to_step1(drv, hard=(setup == "hard"))

            # Capture current screen state before each suite for diagnostics
            try:
                drv.screenshot(f"suite_start_{suite_name}")
                from src.regression.helpers import detect_current_screen
                sid, slabel = detect_current_screen(drv, timeout=2)
                logging.info("[suite:%s] Screen at start: %s", suite_name, slabel)
            except Exception as _e:
                logging.debug("[suite:%s] Pre-suite diagnostic failed: %s", suite_name, _e)

            runner.run_all(tests)

        total = len(runner.results)
        passed = sum(1 for r in runner.results if r.passed)
        logging.info("▶ Overall result: %d/%d passed", passed, total)

        if args.result_json:
            import json as _json
            os.makedirs(os.path.dirname(args.result_json) or ".", exist_ok=True)
            data = {
                "total": total, "passed": passed, "failed": total - passed,
                "results": [
                    {"name": r.name, "passed": r.passed, "message": r.message}
                    for r in runner.results
                ],
            }
            with open(args.result_json, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)

        sys.exit(0 if passed == total else 1)
    finally:
        drv.close()


if __name__ == "__main__":
    main()
