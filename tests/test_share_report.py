"""
Team share report (share_report/build.py): bilingual data → ko/en HTML.

Run: .venv/bin/pytest tests/test_share_report.py -v
"""
import json

import pytest

from share_report.build import KoreanLeft, load_results, render

SCEN = {"groups": [{"id": 1, "name": {"ko": "패치 끊김", "en": "Patch drops"}}],
        "scenarios": [
            {"id": "R01", "group": 1, "star": True, "auto": True, "needs_bt": False, "title": "Patch out of range",
             "how": {"ko": "패치를 멀리", "en": "Move the patch away"}, "check": {"ko": "재연결", "en": "Reconnects"}},
            {"id": "R02", "group": 1, "star": False, "auto": False, "needs_bt": True, "title": "Five minutes",
             "how": {"ko": "5분", "en": "5 min"}, "check": {"ko": "회수", "en": "Backfill"}}]}
REPORT = {"title": {"ko": "결과", "en": "Results"}, "tiles": [{"n": "auto:ledger"}],
          "conclusions": {"R01": {"ko": "결론", "en": "Conclusion"}},
          "sections": [{"type": "table", "title": {"ko": "회귀", "en": "Regression"},
                        "columns": [{"ko": "영역", "en": "Area"}, {"ko": "결과", "en": "Result"}],
                        "rows": [[{"ko": "로그인", "en": "Login"}, {"pill": "pass", "text": "7/7"}]]},
                       {"type": "ledger", "title": {"ko": "시나리오", "en": "Scenarios"}}]}


def test_english_page_has_no_korean_and_counts_results():
    res = {"R01": {"status": "fail", "note": "메모", "note_en": "memo", "by": "automation", "at": 1795150000000}}
    page = render(REPORT, res, "en", "2026-11-20 15:00", scenarios=SCEN)
    assert "Results" in page and "memo" in page and "Recorded with automation" in page
    assert "FAIL 1" in page and "Planned 1" in page and "1/2" in page
    assert "R01</b> Patch out of range — Conclusion" in page


def test_korean_page_uses_korean_note():
    res = {"R01": {"status": "pass", "note": "메모", "note_en": "memo"}}
    page = render(REPORT, res, "ko", "2026-11-20 15:00", scenarios=SCEN)
    assert "메모" in page and "memo" not in page and "실행 예정 1" in page


def test_missing_english_note_stops_the_english_build():
    res = {"R01": {"status": "pass", "note": "메모"}}
    with pytest.raises(KoreanLeft, match="R01"):
        render(REPORT, res, "en", "x", scenarios=SCEN)


def test_korean_left_in_fixed_text_names_the_field():
    bad = json.loads(json.dumps(REPORT))
    bad["sections"][0]["rows"][0][0] = "로그인"
    with pytest.raises(KoreanLeft, match=r"sections\[0\]"):
        render(bad, {}, "en", "x", scenarios=SCEN)


def test_results_from_artifact_dump_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    (d / "R01.json").write_text(json.dumps({"id": "R01", "data": {"status": "pass", "note": "a", "note_en": "b",
                                                                   "updated_by": "claude", "updated_at": 1}}))
    (d / "R02.json").write_text(json.dumps({"id": "R02", "data": {"status": "weird", "updated_by": "u_x"}}))
    res = load_results(tmp_path)
    assert res["R01"] == {"status": "pass", "note": "a", "note_en": "b", "by": "automation", "at": 1}
    assert res["R02"]["status"] == "" and res["R02"]["by"] == "team"


def test_results_from_page_csv(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("﻿ID,결과,메모,메모 (English),기록자,기록 시각\nR01,부분·관찰,가,a,자동화 기록,11. 20. 15:00\nR02,실행 예정,,,,\n",
                 encoding="utf-8")
    res = load_results(p)
    assert res["R01"]["status"] == "partial" and res["R01"]["note_en"] == "a" and res["R01"]["by"] == "automation"
    assert res["R02"]["status"] == ""


def test_shipped_example_report_builds_in_both_languages():
    from pathlib import Path
    from share_report.build import HERE
    rep = json.loads((HERE / "data" / "example_ak.json").read_text(encoding="utf-8"))
    res = load_results(HERE / "data" / rep["results"])
    for lang in ("ko", "en"):
        assert "<h1>" in render(rep, res, lang, "2026-11-20 16:00")
