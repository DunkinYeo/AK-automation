"""
Slack notification module — S-Patch Accurkardia automation
"""
import datetime
import requests


def _post(webhook_url: str, payload: dict):
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception:
        pass


def _mention(mention: str) -> str:
    if not mention:
        return ""
    m = mention.strip()
    if m.startswith("<") or m.startswith("@"):
        return m + " "
    return f"<@{m}> "


def slack_notify(webhook_url: str, text: str, mention: str = ""):
    _post(webhook_url, {"text": _mention(mention) + text})


def slack_run_start(webhook_url: str, serial: str, duration_hours: float,
                    interval_hours: float, mention: str = ""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    injections = int(duration_hours / interval_hours)
    text = (
        f"{_mention(mention)}:rocket: *AccurKardia Automation Started* — {now}\n"
        f"  • Serial: `{serial}`\n"
        f"  • Duration: `{int(duration_hours)}h`\n"
        f"  • Injection interval: `every {interval_hours:.0f}h`\n"
        f"  • Expected injections: `~{injections}`"
    )
    _post(webhook_url, {"text": text})


def slack_injection_notify(webhook_url: str, count: int, symptom: str,
                            elapsed_sec: float, success: bool, error: str = "",
                            mention: str = ""):
    if success:
        text = (
            f":syringe: *Injection #{count}* :large_green_circle: SUCCESS\n"
            f"  • Symptom: `{symptom}`\n"
            f"  • Elapsed: {elapsed_sec}s"
        )
    else:
        text = (
            f"{_mention(mention)}:syringe: *Injection #{count}* :red_circle: FAILED\n"
            f"  • Symptom: `{symptom}`\n"
            f"  • Error: {error}"
        )
    _post(webhook_url, {"text": text})


def slack_run_complete(webhook_url: str, run_id: str, injection_count: int,
                       duration_hours: float, mention: str = ""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    text = (
        f":white_check_mark: *AccurKardia Run Complete* — {now}\n"
        f"  • Run ID: `{run_id}`\n"
        f"  • Duration: `{int(duration_hours)}h`\n"
        f"  • Total injections: `{injection_count}`"
    )
    _post(webhook_url, {"text": text})


def slack_run_failed(webhook_url: str, run_id: str, error: str, mention: str = ""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    text = (
        f"{_mention(mention)}:x: *AccurKardia Run FAILED* — {now}\n"
        f"  • Run ID: `{run_id}`\n"
        f"  • Error: {error}"
    )
    _post(webhook_url, {"text": text})


def slack_urgent_alert(webhook_url: str, message: str, mention: str = ""):
    _post(webhook_url, {"text": f"{_mention(mention)}:rotating_light: *[URGENT] AccurKardia*\n{message}"})


def slack_regression_suite(webhook_url: str, suite: str, passed: int, total: int, failures: list, mention: str = ""):
    icon = ":white_check_mark:" if passed == total else ":x:"
    lines = [f"{icon} *[Regression] {suite}* — {passed}/{total} passed"]
    for f in failures[:5]:
        lines.append(f"  • {f}")
    _post(webhook_url, {"text": "\n".join(lines)})


def slack_daily_report(webhook_url: str, suite_results: dict, injection_result: dict,
                       duration_hours: float = 0, interval_hours: float = 0,
                       injection_count: int = 0):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    inj_ok = (injection_result or {}).get("success", True)
    inj_icon = ":white_check_mark:" if inj_ok else ":x:"
    lines = [f":bar_chart: *AccurKardia Daily Report* — {now}",
             f"  • Duration: `{int(duration_hours)}h` | Interval: `{interval_hours:.0f}h`",
             f"  • Injections: `{injection_count}` {inj_icon}"]
    for suite, r in suite_results.items():
        if r.get("skipped"):
            continue
        icon = ":white_check_mark:" if r["passed"] == r["total"] else ":x:"
        lines.append(f"  • {suite}: {icon} {r['passed']}/{r['total']}")
    _post(webhook_url, {"text": "\n".join(lines)})


def slack_bug_report(webhook_url: str):
    pass
