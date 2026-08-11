"""
Merges a run's app-log capture (#55) with its own automation events
(events.jsonl) into a single time-ordered timeline for the saved report
(#69). Kept separate from reporter.py so the same logic can be reused by
a live-dashboard endpoint later without duplicating it.

App log line format (confirmed against real captures, 2026-08-11 —
591/591 lines matched with zero exceptions, so this is a single fixed
format, not something that needs multiple regex candidates):

    [Tue Aug 11 2026 00:18:48 GMT-0500] [S-Patch AccurKardia] - [Category] [Sub] Message

The timestamp has an explicit GMT offset; events.jsonl's timestamps don't
(naive local time). Both are produced on the same machine, so they're
compared as naive local datetimes here rather than converted to UTC --
simpler, and correct as long as that assumption holds (noted in case a
future multi-machine setup breaks it).
"""
import datetime
import html as _html
import os
import re
import zipfile

_APP_LOG_LINE_RE = re.compile(
    r'^\[\w+ (?P<mon>\w+) (?P<day>\d+) (?P<year>\d+) '
    r'(?P<h>\d+):(?P<m>\d+):(?P<s>\d+) GMT[+-]\d+\] '
    r'\[S-Patch AccurKardia\] - (?P<rest>.*)$'
)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
)}

KEYWORDS = ["error", "fail", "exception", "bluetooth", "disconnect", "upload", "study", "timeout"]
_KEYWORD_RE = re.compile("(" + "|".join(re.escape(k) for k in KEYWORDS) + ")", re.IGNORECASE)


def _parse_app_log_line(line: str):
    m = _APP_LOG_LINE_RE.match(line.strip())
    if not m:
        return None
    mon = _MONTHS.get(m.group("mon"))
    if mon is None:
        return None
    try:
        dt = datetime.datetime(
            int(m.group("year")), mon, int(m.group("day")),
            int(m.group("h")), int(m.group("m")), int(m.group("s")),
        )
    except ValueError:
        return None
    return dt, m.group("rest")


def _find_latest_app_log_zip(out_dir: str) -> str | None:
    """
    A run can have multiple captures (mid-run manual clicks land in
    app_logs/<ts>/<uuid>.zip, the automatic end-of-run one lands directly
    in app_logs/<uuid>.zip) -- each capture is a full re-export from study
    start, so the most recently modified one is always the most complete;
    no need to merge across captures.
    """
    app_logs_dir = os.path.join(out_dir, "app_logs")
    if not os.path.isdir(app_logs_dir):
        return None
    candidates = []
    for root, _dirs, files in os.walk(app_logs_dir):
        for fn in files:
            if fn.endswith(".zip"):
                candidates.append(os.path.join(root, fn))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _load_app_log_entries(out_dir: str):
    """Returns (entries, source_filename, unparsed_count). entries is
    always a list (empty if no capture exists or logs.txt is missing) --
    never raises, so a run with no/broken app log still gets a valid
    (automation-only) timeline."""
    zip_path = _find_latest_app_log_zip(out_dir)
    if not zip_path:
        return [], None, 0

    entries = []
    unparsed = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            raw = zf.read("logs.txt").decode("utf-8", errors="replace")
    except Exception:
        return [], None, 0

    for line in raw.splitlines():
        if not line.strip():
            continue
        parsed = _parse_app_log_line(line)
        if parsed is None:
            unparsed += 1
            continue
        dt, rest = parsed
        entries.append({"ts": dt, "text": rest})

    return entries, os.path.basename(zip_path), unparsed


def _highlight(text: str) -> str:
    escaped = _html.escape(text)
    return _KEYWORD_RE.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)


def _fmt_event_for_timeline(event: dict) -> str:
    name = event.get("event", "")
    data = event.get("data") or {}
    extra = ""
    if event.get("event") == "job_result":
        extra = f" — {'ok' if data.get('success') else 'FAILED'}"
    elif event.get("event") in ("run_failed", "job_failed"):
        extra = f" — {str(data.get('error') or data.get('reason') or '')[:200]}"
    return _highlight(name + extra)


def build_log_timeline(out_dir: str, events: list[dict], run_start_ts: str, run_end_ts: str) -> dict:
    """
    Returns a dict ready for the report template:
      {"rows": [{"ts": iso_str, "source": "auto"|"app", "html": safe_html}, ...],
       "app_log_source": filename or None,
       "unparsed_count": int}
    Safe to call even when no app log was ever captured for this run --
    rows will just be automation-only in that case.
    """
    def _parse_iso(ts: str):
        if not ts:
            return None
        try:
            return datetime.datetime.fromisoformat(ts)
        except ValueError:
            return None

    start_dt = _parse_iso(run_start_ts)
    end_dt = _parse_iso(run_end_ts)

    app_entries, app_log_source, unparsed_count = _load_app_log_entries(out_dir)

    def _in_range(dt: datetime.datetime) -> bool:
        if start_dt and dt < start_dt:
            return False
        if end_dt and dt > end_dt:
            return False
        return True

    if start_dt or end_dt:
        app_entries = [e for e in app_entries if _in_range(e["ts"])]

    rows = []
    for e in events:
        text = e.get("event", "")
        rows.append({
            "ts": e.get("ts", ""), "source": "auto",
            "html": _fmt_event_for_timeline(e),
            # "flagged" lets a caller show a short highlights list (e.g. the
            # mobile-card /api/report) instead of the full row-by-row table
            # reporter.py's summary.html renders.
            "flagged": bool(_KEYWORD_RE.search(text)) or e.get("event") in (
                "run_failed", "job_failed", "session_recovery_failed",
                "ui_health_check_failed",
            ),
        })
    for e in app_entries:
        rows.append({
            "ts": e["ts"].isoformat(timespec="seconds"), "source": "app",
            "html": _highlight(e["text"]),
            "flagged": bool(_KEYWORD_RE.search(e["text"])),
        })

    rows.sort(key=lambda r: r["ts"])

    return {"rows": rows, "app_log_source": app_log_source, "unparsed_count": unparsed_count}
