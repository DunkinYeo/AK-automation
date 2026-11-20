"""
Team share report: one bilingual data file → Korean and English HTML + PDF.

    python -m share_report.build share_report/data/<report>.json            # ko + en
    python -m share_report.build <report>.json --lang en --out output/share
    python -m share_report.build <report>.json --results <db-dump-dir or .csv>

The report file holds the fixed text in both languages ({"ko": .., "en": ..}).
The reconnect ledger reads scenario definitions from reconnect_scenarios.json and
results from a results file (JSON keyed by scenario id, a directory of
ArtifactData JSON dumps, or the results page's CSV export). Each result carries
`note` (Korean) and `note_en` (English); testers write both.

The English output must contain no Hangul: the build stops and names the field
that still has Korean (usually a result without note_en).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HANGUL = re.compile(r"[\uac00-\ud7a3\u3131-\u318e]")
STATUSES = ("pass", "fail", "partial", "blocked", "na")
LABEL = {
    "ko": {"pass": "PASS", "fail": "FAIL", "partial": "부분·관찰", "blocked": "이 폰 불가", "na": "해당 없음", "": "실행 예정"},
    "en": {"pass": "PASS", "fail": "FAIL", "partial": "Partial", "blocked": "Not on this phone", "na": "N/A", "": "Planned"},
}
WORDS = {
    "ko": {"check": "확인: ", "recorded": "기록", "status": "재연결 시나리오 현황", "last": "마지막 기록",
           "automation": "자동화 기록", "team": "팀원", "snapshot": "{at} 기준 사본입니다.",
           "lang": "ko", "ledger_tile": "재연결 시나리오 결과 기록 ({n}개 중)"},
    "en": {"check": "Check: ", "recorded": "recorded", "status": "Reconnection scenario status", "last": "Last record",
           "automation": "Recorded with automation", "team": "Team member", "snapshot": "Snapshot as of {at}.",
           "lang": "en", "ledger_tile": "Reconnection scenarios with a result (of {n})"},
}


class KoreanLeft(ValueError):
    pass


# ── loading ──────────────────────────────────────────────────────────────────

def load_results(path: str | Path | None) -> dict:
    """Results keyed by scenario id: {status, note, note_en, by, at}."""
    if not path:
        return {}
    p = Path(path)
    if p.is_dir():                                   # ArtifactData out_dir dump
        files = sorted(p.rglob("*.json"))
        out = {}
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            out[f.stem] = _norm(d.get("data", d))
        return out
    if p.suffix.lower() == ".csv":                   # results page CSV export
        out = {}
        rev = {v: k for k, v in LABEL["ko"].items()} | {"미실행": ""}
        with p.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                out[row["ID"]] = {"status": rev.get(row.get("결과", ""), ""), "note": row.get("메모", ""),
                                  "note_en": row.get("메모 (English)", ""),
                                  "by": "automation" if row.get("기록자") == "자동화 기록" else ("team" if row.get("기록자") else ""),
                                  "at_text": row.get("기록 시각", "")}
        return out
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: _norm(v) for k, v in data.items()}


def _norm(d: dict) -> dict:
    by = d.get("by")
    if by is None:
        u = d.get("updated_by") or ""
        by = "automation" if u == "claude" else ("team" if u else "")
    st = d.get("status") or ""
    return {"status": st if st in STATUSES else "", "note": d.get("note", ""), "note_en": d.get("note_en", ""),
            "by": by, "at": d.get("at", d.get("updated_at"))}


# ── rendering helpers ────────────────────────────────────────────────────────

class R:
    def __init__(self, lang: str):
        self.lang = lang
        self.w = WORDS[lang]
        self.where = ""                              # field path, for the Hangul check

    def t(self, v, where: str = "") -> str:
        """Pick the language from {"ko","en"} or take a plain string; escape; **bold**."""
        if isinstance(v, dict) and ("ko" in v or "en" in v):
            v = v.get(self.lang, "")
        s = "" if v is None else str(v)
        if self.lang == "en" and HANGUL.search(s):
            raise KoreanLeft(f"Korean text left in {where or self.where}: {s[:80]!r}")
        s = html.escape(s, quote=True)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    def cell(self, c, where: str) -> str:
        if isinstance(c, list):
            return " ".join(self.cell(x, where) for x in c)
        if isinstance(c, dict) and "pill" in c:
            pill = f'<span class="pill {html.escape(c["pill"])}">{self.t(c.get("text", ""), where)}</span>'
            return pill + (" " + self.t(c["after"], where) if c.get("after") else "")
        if isinstance(c, dict) and "br" in c:
            return "<br>"
        return self.t(c, where)


def fmt_at(ms) -> str:
    if not ms:
        return ""
    try:
        return dt.datetime.fromtimestamp(float(ms) / 1000).strftime("%m/%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def render(report: dict, results: dict, lang: str, stamp: str, scenarios: dict | None = None) -> str:
    r = R(lang)
    w = r.w
    scen_file = scenarios or (json.loads((HERE / "reconnect_scenarios.json").read_text(encoding="utf-8"))
                              if any(s.get("type") == "ledger" for s in report.get("sections", [])) else None)
    scen = scen_file["scenarios"] if scen_file else []
    done = [s for s in scen if results.get(s["id"], {}).get("status")]

    meta = "".join(f'<span>{r.t(m["label"], "meta")} <b>{r.t(m["value"], "meta")}</b></span>' for m in report.get("meta", []))
    tiles = ""
    for i, tl in enumerate(report.get("tiles", [])):
        n = tl.get("n", "")
        label = tl.get("l", "")
        if n == "auto:ledger":
            n, label = f"{len(done)}/{len(scen)}", w["ledger_tile"].format(n=len(scen))
        tiles += f'<div class="tile"><div class="n">{r.t(n, f"tiles[{i}]")}</div><div class="l">{r.t(label, f"tiles[{i}]")}</div></div>'

    summary = ""
    if scen:
        cnt = {k: sum(1 for s in done if results[s["id"]]["status"] == k) for k in STATUSES}
        pills = "".join(f'<span class="pill {k}">{LABEL[lang][k]} {cnt[k]}</span>' for k in STATUSES if cnt[k] or k in ("pass", "fail"))
        pills += f'<span class="pill none">{LABEL[lang][""]} {len(scen) - len(done)}</span>'
        issues = ""
        for s in done:
            res = results[s["id"]]
            if res["status"] not in ("fail", "partial"):
                continue
            concl = report.get("conclusions", {}).get(s["id"])
            concl = r.t(concl, f"conclusions.{s['id']}") if concl else ""
            issues += (f'<li><span class="pill {res["status"]}">{LABEL[lang][res["status"]]}</span> <b>{s["id"]}</b> '
                       f'{r.t(s["title"], s["id"] + ".title")}{" — " + concl if concl else ""}</li>')
        last = max([results[s["id"]].get("at") or 0 for s in done] or [0])
        summary = f'''<div class="rsum"><div class="rsum-h"><b>{w["status"]}</b><span class="legend">{w["last"] + " " + fmt_at(last) if last else ""}</span></div>
<div class="rsum-c">{pills}</div>{f'<ul class="facts">{issues}</ul>' if issues else ""}</div>'''

    note = r.t(report.get("snapshot_note", ""), "snapshot_note")
    head = f'''<header class="hero"><div class="hero-in">
<div class="eyebrow">{r.t(report.get("eyebrow", ""), "eyebrow")}</div>
<h1>{r.t(report["title"], "title")}</h1>
<div class="meta">{meta}</div>
<p class="legend" style="margin:0">{w["snapshot"].format(at=stamp)} {note}</p>
<div class="tiles">{tiles}</div>{summary}</div></header>'''

    body = ""
    for si, sec in enumerate(report.get("sections", [])):
        where = f"sections[{si}]"
        kind = sec.get("type")
        sub = f' <span class="legend" style="font-weight:400">· {r.t(sec["subtitle"], where)}</span>' if sec.get("subtitle") else ""
        h2 = f'<h2>{r.t(sec.get("title", ""), where)}{sub}</h2>' if sec.get("title") else ""
        if kind == "table":
            ths = "".join(f"<th>{r.t(c, where)}</th>" for c in sec["columns"])
            trs = ""
            for row in sec["rows"]:
                tds = ""
                for ci, c in enumerate(row):
                    cls = ' class="num"' if ci in sec.get("num_cols", []) else ""
                    tds += f"<td{cls}>{r.cell(c, where)}</td>"
                trs += f"<tr>{tds}</tr>"
            foot = f'<p class="legend" style="margin:10px 0 0">{r.t(sec["footnote"], where)}</p>' if sec.get("footnote") else ""
            body += f'<section>{h2}<div class="panel scroll"><table class="res"><tr>{ths}</tr>{trs}</table>{foot}</div></section>'
        elif kind == "key":
            tl = "".join(f"<tr><td>{html.escape(a)}</td><td>{r.t(b, where)}</td></tr>" for a, b in sec.get("timeline", []))
            blocks = ""
            for bi, b in enumerate(sec.get("blocks", [])):
                items = "".join(f"<li>{r.t(x, where)}</li>" for x in b["items"])
                blocks += f'<h3{" style=margin-top:12px" if bi else ""}>{r.t(b["title"], where)}</h3><ul class="facts">{items}</ul>'
            verdict = sec.get("verdict", "")
            body += f'''<section style="display:grid;gap:16px">{h2}<section class="panel key">
<h3 style="font-size:16px;margin-bottom:10px"><span class="verdict">{r.t(sec["heading"], where)} <span class="pill {verdict}">{LABEL[lang].get(verdict, "")}</span></span></h3>
<p style="margin:0 0 10px;color:var(--muted)">{r.t(sec.get("intro", ""), where)}</p>
<div class="two"><div class="scroll"><table class="tl">{tl}</table></div><div>{blocks}</div></div></section></section>'''
        elif kind == "ledger":
            groups = ""
            for g in scen_file["groups"]:
                rows = [s for s in scen if s["group"] == g["id"]]
                got = sum(1 for s in rows if results.get(s["id"], {}).get("status"))
                groups += f'<div class="grp"><div class="grp-h"><h3>{r.t(g["name"], "groups")}</h3><span>{got}/{len(rows)} {w["recorded"]}</span></div>'
                for s in rows:
                    res = results.get(s["id"], {})
                    st = res.get("status", "")
                    note_txt = res.get("note_en" if lang == "en" else "note", "") or ""
                    if lang == "en" and res.get("note") and not note_txt:
                        raise KoreanLeft(f"{s['id']}: result has a Korean note but no note_en")
                    who = {"automation": w["automation"], "team": w["team"]}.get(res.get("by", ""), "")
                    at = fmt_at(res.get("at")) or res.get("at_text", "")
                    by = f'<div class="by">{who + " · " if who else ""}{at}</div>' if at else ""
                    tags = ('<span class="pill auto">' + ("자동" if lang == "ko" else "Auto") + "</span>" if s.get("auto") else "") + \
                           ('<span class="pill na">BT</span>' if s.get("needs_bt") else "")
                    groups += f'''<div class="row"><div class="id">{s["id"]}{'<span class="star">★</span>' if s.get("star") else ""}</div>
<div style="min-width:0"><div class="t">{r.t(s["title"], s["id"])}</div><div class="how">{r.t(s["how"], s["id"] + ".how")}</div>
<div class="chk">{r.t(s["check"], s["id"] + ".check")}</div>{f'<div class="note">{r.t(note_txt, s["id"] + ".note_en")}</div>' if note_txt else ""}{by}</div>
<div class="side"><span class="pill {st or "none"}">{LABEL[lang][st]}</span><div class="tags">{tags}</div></div></div>'''
                groups += "</div>"
            legend = f'<div class="legend">{r.t(sec["legend"], where)}</div>' if sec.get("legend") else ""
            body += f"<section>{h2}{legend}{groups}</section>"
        elif kind == "list":
            items = "".join(f"<li>{r.t(x, where)}</li>" for x in sec["items"])
            body += f'<section class="panel">{h2}<ul class="facts">{items}</ul></section>'
        else:
            raise ValueError(f"{where}: unknown section type {kind!r}")

    css = (HERE / "style.css").read_text(encoding="utf-8").replace("{{CHECK}}", w["check"])
    font = "IBM+Plex+Sans+KR" if lang == "ko" else "IBM+Plex+Sans"
    fonts = f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={font}:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">'
    title = r.t(report["title"], "title")
    out = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>{title}</title>{fonts}<style>{css}</style></head><body>{head}<main class=\"wrap\">{body}</main></body></html>")
    if lang == "en" and HANGUL.search(out):
        raise KoreanLeft("Korean text left in the English page: " + ", ".join(sorted(set(HANGUL.findall(out)))[:20]))
    return out


# ── PDF ──────────────────────────────────────────────────────────────────────

def find_chrome() -> str | None:
    for c in (os.environ.get("CHROME_PATH"),
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if c and Path(c).exists():
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def to_pdf(html_path: Path, pdf_path: Path) -> bool:
    chrome = find_chrome()
    if not chrome:
        return False
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=8000", f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
    return pdf_path.exists() and pdf_path.stat().st_size > 0


def build(report_path: str | Path, results_path=None, langs=("ko", "en"), out_dir="output/share", pdf=True) -> list[Path]:
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rp = results_path or report.get("results")
    if rp and not Path(rp).is_absolute() and not Path(rp).exists():
        rp = report_path.parent / rp
    results = load_results(rp)
    now = dt.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for lang in langs:
        page = render(report, results, lang, stamp)
        base = report.get("file_name", {}).get(lang) or f"{report_path.stem}_{lang}"
        base = f"{base}_{now:%Y%m%d_%H%M}"
        hp = out / f"{base}.html"
        hp.write_text(page, encoding="utf-8")
        made.append(hp)
        if pdf:
            pp = out / f"{base}.pdf"
            if to_pdf(hp, pp):
                made.append(pp)
            else:
                print("PDF skipped: Chrome/Edge not found (set CHROME_PATH). Open the HTML and print to PDF.", file=sys.stderr)
    return made


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--results", help="results JSON, ArtifactData dump directory, or results-page CSV")
    ap.add_argument("--lang", choices=["ko", "en", "both"], default="both")
    ap.add_argument("--out", default="output/share")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    langs = ("ko", "en") if a.lang == "both" else (a.lang,)
    try:
        for p in build(a.report, a.results, langs, a.out, pdf=not a.no_pdf):
            print(p)
    except KoreanLeft as e:
        print("English version stopped:", e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
