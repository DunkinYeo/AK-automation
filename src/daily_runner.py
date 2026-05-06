#!/usr/bin/env python3
"""
S-Patch VM Daily Runner

매일 자동 실행:
  1. Regression suites (serial, menu — 항상)
  2. Regression suites (main, diary — 검사 진행 중일 때)
  3. Injection 1회 검증 (검사 진행 중일 때)
  4. Slack 결과 리포트

Usage:
    python src/daily_runner.py --config config/spatch-vm.yaml
"""
import argparse
import logging
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .env 로드 (python-dotenv 없어도 직접 파싱)
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
from src.regression.runner import TestRunner
from src.regression import serial_input, menu_step1, main_screen, add_diary, menu_study
from src.regression.helpers import reset_to_step1
from src.workflows.measurement_start import ensure_on_main_screen
from src.workflows.symptom_inject import inject_symptom_event
from src.slack import slack_daily_report, slack_bug_report, slack_urgent_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# suite명: (tests, require_study)
SUITES = {
    "serial":     (serial_input.TESTS, False),
    "menu":       (menu_step1.TESTS,   False),
    "main":       (main_screen.TESTS,  True),
    "diary":      (add_diary.TESTS,    True),
    "menu-study": (menu_study.TESTS,   True),
}

_CONSECUTIVE_FAIL_THRESHOLD = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/spatch-vm.yaml")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    a_cfg     = cfg.get("android", {})
    selectors = cfg.get("selectors", {}).get("android", {})
    slack_cfg = cfg.get("slack", {})
    webhook   = (
        os.environ.get("SLACK_WEBHOOK_URL") or slack_cfg.get("webhook_url", "")
    ) if slack_cfg.get("enabled") else ""

    out_dir = "output/daily"
    os.makedirs(out_dir, exist_ok=True)

    artifacts = ArtifactManager(out_dir=out_dir)
    reporter  = RunReporter(out_dir=out_dir, run_name="daily")
    drv       = AndroidDriver(a_cfg, selectors, artifacts, reporter)

    suite_results = {}
    injection_result = None

    try:
        runner = TestRunner(drv, artifacts)

        # ── 검사 진행 중 여부 확인 ────────────────────────────────
        study_running = False
        try:
            ensure_on_main_screen(drv)
            study_running = True
            log.info("[daily] 검사 진행 중 — 전체 suite 실행")
        except Exception:
            log.info("[daily] 검사 미진행 — serial/menu suite만 실행")

        # ── Regression suites ─────────────────────────────────────
        # 검사 진행 중: Step 1 복귀 불가 → serial/menu 스킵, main/diary 실행
        # 검사 미진행: serial/menu 실행, main/diary 스킵
        for suite_name, (tests, require_study) in SUITES.items():
            if require_study and not study_running:
                suite_results[suite_name] = {"passed": 0, "total": 0, "skipped": True}
                continue
            if not require_study and study_running:
                suite_results[suite_name] = {"passed": 0, "total": 0, "skipped": True}
                continue

            log.info("=" * 50)
            log.info("Suite: %s", suite_name)

            if not require_study:
                reset_to_step1(drv, hard=True)
            else:
                # suite 전환 전 메인 화면 재확인
                ensure_on_main_screen(drv)

            pre_count = len(runner.results)
            runner.run_all(tests)
            suite_results_list = runner.results[pre_count:]

            passed   = sum(1 for r in suite_results_list if r.passed)
            total    = len(suite_results_list)
            failures = [r.message for r in suite_results_list if not r.passed]

            suite_results[suite_name] = {
                "passed": passed,
                "total": total,
                "failures": failures,
                "_results": suite_results_list,
            }

        # ── Injection 검증 (검사 진행 중일 때만) ─────────────────
        if study_running:
            try:
                ensure_on_main_screen(drv)
                import time, random
                from src.workflows.symptom_inject import SYMPTOMS, ACTIVITIES
                symptom  = random.choice(SYMPTOMS)
                activity = random.choice(ACTIVITIES)
                t = time.monotonic()
                inject_symptom_event(drv, symptoms=[symptom], activities=[activity])
                injection_result = {
                    "success": True,
                    "symptom": symptom,
                    "activity": activity,
                    "elapsed_sec": round(time.monotonic() - t, 1),
                }
            except Exception as e:
                injection_result = {"success": False, "error": str(e)}

        # ── 연속 실패 체크 ────────────────────────────────────────
        all_failures = [
            r.message
            for v in suite_results.values()
            if not v.get("skipped")
            for r in (v.get("_results") or [])
            if not r.passed
        ]
        if webhook and len(all_failures) >= _CONSECUTIVE_FAIL_THRESHOLD:
            slack_urgent_alert(
                webhook,
                f"{len(all_failures)}개 테스트 실패 감지\n"
                + "\n".join(f"• {m}" for m in all_failures[:5])
            )

        # ── Slack 리포트 ──────────────────────────────────────────
        if webhook:
            slack_daily_report(webhook, suite_results, injection_result)
            slack_bug_report(webhook)
            log.info("[daily] Slack 알림 전송 완료")
        else:
            log.info("[daily] Slack 비활성화 — 알림 스킵")

        # 결과 출력
        total_p = sum(v["passed"] for v in suite_results.values() if not v.get("skipped"))
        total_t = sum(v["total"]  for v in suite_results.values() if not v.get("skipped"))
        log.info("▶ Daily 결과: %d/%d passed", total_p, total_t)

    finally:
        drv.close()


if __name__ == "__main__":
    main()
