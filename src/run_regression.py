#!/usr/bin/env python3
"""
S-Patch Accurkardia Regression Test Runner

Usage:
    # 기기 연결 불필요
    python src/run_regression.py --suite serial
    python src/run_regression.py --suite menu

    # 검사 미등록 + BLE 연결 필요
    python src/run_regression.py --suite signal
    python src/run_regression.py --suite study

    # 검사 진행 중 필요
    python src/run_regression.py --suite main
    python src/run_regression.py --suite diary
    python src/run_regression.py --suite menu-study
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
from src.regression import serial_input, menu_step1, signal_check, study_popup, main_screen, add_diary, menu_study
from src.regression.helpers import reset_to_step1, go_to_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# (tests, setup)
# setup="hard"  : 앱 강제 재시작 → Step 1
# setup="soft"  : 뒤로가기 → Step 1 (BLE 유지)
# setup="main"  : Step 1 → Connect → Step 3 → 측정 메인 화면 (BLE + 스터디 등록 필요)
SUITES = {
    "serial": (serial_input.TESTS,  "hard"),
    "menu":   (menu_step1.TESTS,    "hard"),
    "signal": (signal_check.TESTS,  "soft"),
    "study":  (study_popup.TESTS,   "soft"),
    "main":       (main_screen.TESTS,  "main"),  # Step 1 → 연결 → 측정 메인 화면
    "diary":      (add_diary.TESTS,    "main"),  # Step 1 → 연결 → 측정 메인 화면
    "menu-study": (menu_study.TESTS,   "main"),  # Step 1 → 연결 → 측정 메인 화면
}


def main():
    parser = argparse.ArgumentParser(description="S-Patch Accurkardia Regression Test Runner")
    parser.add_argument("--config", default="config/accurkardia.yaml")
    parser.add_argument(
        "--suite",
        choices=list(SUITES.keys()) + ["all"],
        default="all",
        help="실행할 테스트 suite (기본: all)",
    )
    args = parser.parse_args()

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

        if args.suite == "all":
            suite_list = list(SUITES.items())
        else:
            suite_list = [(args.suite, SUITES[args.suite])]

        last_summary = {}
        for suite_name, (tests, setup) in suite_list:
            logging.info("=" * 50)
            logging.info("Suite: %s (%d tests)", suite_name, len(tests))
            logging.info("=" * 50)
            if setup == "none":
                pass  # 현재 화면 그대로 (측정 중 화면 유지)
            elif setup == "main":
                reset_to_step1(drv, hard=True)
                go_to_main(drv)
            else:
                reset_to_step1(drv, hard=(setup == "hard"))
            last_summary = runner.run_all(tests)

        total = len(runner.results)
        passed = sum(1 for r in runner.results if r.passed)
        logging.info("▶ 전체 결과: %d/%d passed", passed, total)
        sys.exit(0 if passed == total else 1)
    finally:
        drv.close()


if __name__ == "__main__":
    main()
