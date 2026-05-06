"""
Slack 알림 모듈 — S-Patch Accurkardia 자동화
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
        f"  • Expected injections: `~{injections}회`"
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
        f"  • Total injections: `{injection_count}회`"
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
