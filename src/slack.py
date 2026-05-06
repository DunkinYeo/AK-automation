"""
Slack 알림 모듈 — S-Patch VM 자동화 리포트
"""
import datetime
import requests

# 확인된 앱 버그 목록 (TC ID, 설명, 재현 조건)
KNOWN_BUGS = [
    {
        "id": "TC-SN-003",
        "title": "5자리 입력 시 Connect 버튼 활성화",
        "detail": "시리얼 넘버 5자리 입력 시 Connect 버튼이 활성화됨 (6자리에서만 활성화되어야 함)",
    },
    {
        "id": "TC-SN-005",
        "title": "영문 입력 시 Connect 버튼 활성화",
        "detail": "영문(ABCDEF) 입력 시 Connect 버튼이 활성화됨 (숫자만 허용되어야 함)",
    },
]


def _post(webhook_url: str, payload: dict):
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception:
        pass


def slack_notify(webhook_url: str, text: str):
    _post(webhook_url, {"text": text})


def slack_run_start(webhook_url: str, serial: str, duration_hours: float, interval_hours: float):
    """자동화 시작 시 설정 내용 Slack 알림."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    injections = int(duration_hours / interval_hours)
    text = (
        f":rocket: *S-Patch VM Automation Started* — {now}\n"
        f"  • Serial: `{serial}`\n"
        f"  • Duration: `{int(duration_hours)}h`\n"
        f"  • Injection interval: `every {interval_hours:.0f}h`\n"
        f"  • Expected injections: `~{injections}회`"
    )
    _post(webhook_url, {"text": text})


def slack_injection_notify(webhook_url: str, count: int, symptom: str, activity: str,
                           elapsed_sec: float, success: bool, error: str = ""):
    """매 주입 결과 Slack 알림."""
    if success:
        text = (
            f":syringe: *Injection #{count}* :large_green_circle: SUCCESS\n"
            f"  • Symptom: `{symptom}`\n"
            f"  • Activity: `{activity}`\n"
            f"  • Elapsed: {elapsed_sec}s"
        )
    else:
        text = (
            f":syringe: *Injection #{count}* :red_circle: FAILED\n"
            f"  • Symptom: `{symptom}`\n"
            f"  • Activity: `{activity}`\n"
            f"  • Error: {error}"
        )
    _post(webhook_url, {"text": text})


def slack_regression_suite(webhook_url: str, suite: str, passed: int, total: int, failures: list):
    """각 regression suite 완료 직후 결과 알림."""
    if total == 0:
        return
    if passed == total:
        icon = ":large_green_circle:"
        status = "PASS"
    else:
        icon = ":red_circle:"
        status = "FAIL"
    lines = [f"{icon} *[Regression] {suite}* — {passed}/{total} {status}"]
    for msg in failures:
        lines.append(f"  • {msg}")
    _post(webhook_url, {"text": "\n".join(lines)})


def slack_bug_report(webhook_url: str):
    """알려진 버그 목록 Slack 전송."""
    lines = [f":bug: *S-Patch VM Bug Report* — {len(KNOWN_BUGS)}건 확인됨\n"]
    for bug in KNOWN_BUGS:
        lines.append(f"• *[{bug['id']}]* {bug['title']}\n  _{bug['detail']}_")
    _post(webhook_url, {"text": "\n".join(lines)})


def slack_urgent_alert(webhook_url: str, message: str):
    """긴급 알림 (연속 실패 등)."""
    _post(webhook_url, {"text": f":rotating_light: *[URGENT] S-Patch VM*\n{message}"})


def slack_daily_report(webhook_url: str, suite_results: dict, injection: dict | None = None,
                       duration_hours: float = None, interval_hours: float = None,
                       injection_count: int = None):
    """
    일일 자동화 결과 Slack 전송.

    suite_results: { "serial": {"passed": 6, "total": 6, "skipped": False}, ... }
    injection: {"symptom": ..., "activity": ..., "elapsed_sec": ..., "success": True} or None
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    total_passed = sum(v["passed"] for v in suite_results.values() if not v.get("skipped"))
    total_tests  = sum(v["total"]  for v in suite_results.values() if not v.get("skipped"))
    all_pass     = total_passed == total_tests

    header_icon = ":white_check_mark:" if all_pass else ":x:"
    header_text = f"{header_icon} *S-Patch VM Daily Report* — {now}"

    # Suite 결과 라인
    suite_lines = []
    for suite, r in suite_results.items():
        if r.get("skipped"):
            suite_lines.append(f"  :white_circle: `{suite}`: skipped")
        elif r["passed"] == r["total"]:
            suite_lines.append(f"  :large_green_circle: `{suite}`: {r['passed']}/{r['total']} PASS")
        else:
            suite_lines.append(f"  :red_circle: `{suite}`: {r['passed']}/{r['total']} FAIL")
            for msg in r.get("failures", []):
                suite_lines.append(f"      • {msg}")

    regression_block = "*Regression Results:*\n" + "\n".join(suite_lines)

    # Injection 결과
    if injection:
        if injection.get("success"):
            inj_text = (
                f"*Injection Test:* :large_green_circle: "
                f"`{injection['symptom']}` + `{injection['activity']}` "
                f"({injection.get('elapsed_sec', '?')}s)"
            )
        else:
            inj_text = f"*Injection Test:* :red_circle: FAIL — {injection.get('error', '')}"
    else:
        inj_text = "*Injection Test:* :white_circle: skipped"

    # 설정 정보
    config_parts = []
    if duration_hours is not None:
        config_parts.append(f"Duration: `{int(duration_hours)}h`")
    if interval_hours is not None:
        config_parts.append(f"Interval: `every {interval_hours:.0f}h`")
    if injection_count is not None:
        config_parts.append(f"Total injections: `{injection_count}회`")
    config_text = "  •  ".join(config_parts) if config_parts else None

    summary = f"*Total: {total_passed}/{total_tests} passed*"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": regression_block}},
        {"type": "section", "text": {"type": "mrkdwn", "text": inj_text}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
    ]
    if config_text:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": config_text}]})

    _post(webhook_url, {"blocks": blocks})
