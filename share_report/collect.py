"""
Fill the share report from the runs' own records (output/<run>/events.jsonl).

A report file asks for generated parts with placeholders:
    {"type": "auto_regression"}   → regression table, latest result per suite
    {"type": "auto_longrun"}      → one row per long run
    tile {"n": "auto:regression"} → passed/total over those suites
    tile {"n": "auto:symptoms"}   → symptom entries succeeded / tried
`--since` / `--until` (YYYY-MM-DD or YYYY-MM-DDTHH:MM) pick the runs.
Suite failures are copied as the app automation wrote them (English).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SUITE_LABEL = {
    "login": {"ko": "Step 1 · MC ID/PIN 입력", "en": "Step 1 · MC ID / PIN input"},
    "menu": {"ko": "Settings (Step 1)", "en": "Settings (Step 1)"},
    "link": {"ko": "연결 → 스터디 시작", "en": "Connect → start study"},
    "study": {"ko": "스터디 시작", "en": "Study start"},
    "main": {"ko": "메인 화면 (스터디 중)", "en": "Main screen (during study)"},
    "diary": {"ko": "Log Symptoms (diary)", "en": "Log Symptoms (diary)"},
    "menu-study": {"ko": "스터디 중 메뉴", "en": "Menu during study"},
    "connectivity": {"ko": "연결성 (BT / Wi-Fi)", "en": "Connectivity (BT / Wi-Fi)"},
    "signal": {"ko": "신호 확인 (Step 2)", "en": "Signal check (Step 2)"},
    "resilience": {"ko": "복원력 (화면 끄기 / 종료)", "en": "Resilience (screen off / kill)"},
}
SUITE_ORDER = list(SUITE_LABEL)


@dataclass
class Run:
    id: str
    events: list = field(default_factory=list)

    @property
    def start(self) -> str:
        return self.events[0]["ts"] if self.events else ""

    @property
    def end(self) -> str:
        return self.events[-1]["ts"] if self.events else ""

    def of(self, *names) -> list:
        return [e for e in self.events if e.get("event") in names]


def load_runs(output_dir: str | Path, since: str = "", until: str = "") -> list[Run]:
    runs = []
    for p in sorted(Path(output_dir).glob("*/events.jsonl")):
        evs = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("ts"):
                evs.append(e)
        if not evs:
            continue
        r = Run(p.parent.name, evs)
        if since and r.end < since:
            continue
        if until and r.start > until + ("T99" if "T" not in until else ""):
            continue
        runs.append(r)
    return runs


def hhmm(ts: str) -> str:
    return ts[11:16] if len(ts) >= 16 else ts


# ── regression ───────────────────────────────────────────────────────────────

def regression(runs: list[Run], since: str = "", until: str = "") -> dict:
    """Latest non-skipped result per suite: {suite: {passed, total, failures, ts, run}}."""
    out: dict = {}
    for r in runs:
        for e in r.of("regression_suite_result"):
            if (since and e["ts"] < since) or (until and e["ts"][:len(until)] > until):
                continue
            d = e.get("data", {})
            if d.get("skipped") or not d.get("total"):
                continue
            s = d.get("suite", "?")
            if s not in out or e["ts"] >= out[s]["ts"]:
                out[s] = {"passed": int(d.get("passed", 0)), "total": int(d.get("total", 0)),
                          "failures": list(d.get("failures") or []), "ts": e["ts"], "run": r.id}
    return out


def regression_section(reg: dict, title=None, subtitle=None) -> dict:
    rows = []
    for s in sorted(reg, key=lambda k: (SUITE_ORDER.index(k) if k in SUITE_ORDER else 99, k)):
        v = reg[s]
        ok = v["passed"] == v["total"]
        fails = "; ".join(str(f) for f in v["failures"][:3]) + (" …" if len(v["failures"]) > 3 else "")
        when = {"ko": f"{v['ts'][:10]} {hhmm(v['ts'])} run", "en": f"{v['ts'][:10]} {hhmm(v['ts'])} run"}
        evidence = {"ko": f"{when['ko']}" + (f" · 실패: {fails}" if fails else " · 실패 없음"),
                    "en": f"{when['en']}" + (f" · failed: {fails}" if fails else " · no failures")}
        rows.append([SUITE_LABEL.get(s, s), {"pill": "pass" if ok else "fail", "text": f"{v['passed']}/{v['total']}"}, evidence])
    if not rows:
        rows = [[{"ko": "이 기간의 회귀 결과 없음", "en": "No regression results in this period"}, "—", "—"]]
    return {"type": "table", "title": title or {"ko": "회귀 테스트", "en": "Regression tests"},
            **({"subtitle": subtitle} if subtitle else {}),
            "columns": [{"ko": "영역", "en": "Area"}, {"ko": "결과", "en": "Result"}, {"ko": "근거", "en": "Evidence"}],
            "num_cols": [1], "rows": rows}


# ── long run ─────────────────────────────────────────────────────────────────

def is_longrun(r: Run) -> bool:
    return bool(r.of("scheduler_started", "job_start", "job_result"))


def longrun_row(r: Run) -> list:
    sym_ok = [e for e in r.of("job_result") if e.get("data", {}).get("job_name") == "symptom_inject"]
    ok = sum(1 for e in sym_ok if e["data"].get("success"))
    names = sorted({e["data"].get("symptom") for e in r.of("inject_done") if e.get("data", {}).get("symptom")})
    sym = {"pill": "pass" if sym_ok and ok == len(sym_ok) else ("fail" if sym_ok else "na"),
           "text": f"{ok}/{len(sym_ok)}", **({"after": ", ".join(names)} if names else {})}

    conn = []
    air_done, air_bad = r.of("airplane_mode_done"), r.of("airplane_mode_aborted", "airplane_mode_failed")
    recon = [e["data"].get("elapsed_sec") for e in r.of("bluetooth_reconnected") if e.get("data", {}).get("elapsed_sec") is not None]
    if air_done or air_bad:
        txt = {"ko": f"비행기 {len(air_done)}/{len(air_done) + len(air_bad)}", "en": f"Airplane {len(air_done)}/{len(air_done) + len(air_bad)}"}
        after = {"ko": "자동 재연결 " + ", ".join(f"{s}초" for s in recon), "en": "auto reconnect " + ", ".join(f"{s} s" for s in recon)} if recon else None
        conn.append({"pill": "pass" if not air_bad else "partial", "text": txt, **({"after": after} if after else {})})
    bt_done, bt_bad = r.of("bt_disconnect_done"), r.of("bt_disconnect_failed", "bt_disconnect_aborted", "bt_not_restored")
    if r.of("bt_disconnect_not_supported"):
        conn += ([{"br": 1}] if conn else []) + [{"pill": "blocked", "text": {"ko": "BT 불가", "en": "BT not possible"},
                                                  "after": {"ko": "adb로 BT가 꺼지지 않음", "en": "adb cannot turn BT off"}}]
    elif bt_done or bt_bad:
        conn += ([{"br": 1}] if conn else []) + [{"pill": "pass" if not bt_bad else "fail",
                                                  "text": f"BT {len(bt_done)}/{len(bt_done) + len(bt_bad)}"}]

    cap_ok, cap_bad = r.of("capture_logs_success"), r.of("capture_logs_failed")
    if cap_ok:
        mb = cap_ok[-1].get("data", {}).get("zip_mb")
        cap = {"pill": "pass", "text": {"ko": "성공", "en": "OK"}, **({"after": f"{mb}MB"} if mb else {})}
    elif cap_bad:
        cap = {"pill": "fail", "text": {"ko": "실패", "en": "Failed"}}
    else:
        cap = "—"

    end = r.of("run_failed", "run_complete", "run_ended_study_complete")
    if not end:
        note = {"ko": "종료 기록 없음 (중단 또는 진행 중)", "en": "No end record (stopped or still running)"}
    elif end[-1]["event"] == "run_failed":
        err = str(end[-1].get("data", {}).get("error", ""))[:140]
        note = {"ko": f"실패로 종료: {err}", "en": f"Ended with an error: {err}"}
    elif end[-1]["event"] == "run_ended_study_complete":
        note = {"ko": "스터디 종료로 끝남", "en": "Ended at study end"}
    else:
        note = {"ko": "정상 종료", "en": "Completed"}
    crashes = len(r.of("app_crashed"))
    if crashes:
        note = {"ko": note["ko"] + f" · 앱 크래시 {crashes}회", "en": note["en"] + f" · app crashed {crashes}×"}
    when = f"{r.start[5:10].replace('-', '/')} {hhmm(r.start)}–{hhmm(r.end)}"
    return [when, sym, conn or "—", cap, note]


def longrun_section(runs: list[Run], title=None, subtitle=None) -> dict:
    rows = [longrun_row(r) for r in runs if is_longrun(r)]
    if not rows:
        rows = [[{"ko": "이 기간의 장기런 없음", "en": "No long runs in this period"}, "—", "—", "—", "—"]]
    return {"type": "table", "title": title or {"ko": "장기런", "en": "Long run"},
            **({"subtitle": subtitle} if subtitle else {}),
            "columns": [{"ko": "런", "en": "Run"}, {"ko": "증상 입력", "en": "Symptom entry"},
                        {"ko": "BT / 비행기 모드", "en": "BT / airplane mode"},
                        {"ko": "종료 시 앱 로그 추출", "en": "App log export at end"}, {"ko": "비고", "en": "Notes"}],
            "num_cols": [0], "rows": rows}


# ── expand placeholders ──────────────────────────────────────────────────────

def expand(report: dict, output_dir: str | Path, since: str = "", until: str = "") -> dict:
    runs = load_runs(output_dir, since, until)
    reg = regression(runs, since, until)
    sections = []
    for s in report.get("sections", []):
        if s.get("type") == "auto_regression":
            sections.append(regression_section(reg, s.get("title"), s.get("subtitle")))
        elif s.get("type") == "auto_longrun":
            sec = longrun_section(runs, s.get("title"), s.get("subtitle"))
            if s.get("footnote"):
                sec["footnote"] = s["footnote"]
            sections.append(sec)
        else:
            sections.append(s)
    tiles = []
    for t in report.get("tiles", []):
        if t.get("n") == "auto:regression":
            p, tot = sum(v["passed"] for v in reg.values()), sum(v["total"] for v in reg.values())
            t = {"n": f"{p}/{tot}", "l": t.get("l") or {"ko": "회귀 TC 통과", "en": "Regression TCs passed"}}
        elif t.get("n") == "auto:symptoms":
            jobs = [e for r in runs for e in r.of("job_result") if e.get("data", {}).get("job_name") == "symptom_inject"]
            ok = sum(1 for e in jobs if e["data"].get("success"))
            n_lr = sum(1 for r in runs if is_longrun(r))
            t = {"n": f"{ok}/{len(jobs)}", "l": t.get("l") or {"ko": f"장기런 증상 입력 성공 (장기런 {n_lr}회)",
                                                               "en": f"Long-run symptom entries succeeded ({n_lr} long runs)"}}
        tiles.append(t)
    return {**report, "sections": sections, "tiles": tiles}
