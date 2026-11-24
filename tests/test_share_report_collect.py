"""
Share report auto-fill from run records (share_report/collect.py), the
regression_suite_result event from run_regression.py, and the dashboard routes.

Run: .venv/bin/pytest tests/test_share_report_collect.py -v
"""
import json
from types import SimpleNamespace

from share_report.build import render
from share_report.collect import expand, load_runs, regression


def _run(tmp, name, events):
    d = tmp / name
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps({"ts": t, "event": e, "data": data}) for t, e, data in events) + "\n")


def _fixture(tmp):
    _run(tmp, "20261120_105607", [
        ("2026-11-20T10:56:07", "run_start", {}),
        ("2026-11-20T10:56:14", "regression_suite_result", {"suite": "login", "passed": 0, "total": 0, "failures": [], "skipped": True}),
        ("2026-11-20T10:56:30", "scheduler_started", {}),
        ("2026-11-20T10:57:11", "inject_done", {"symptom": "Irregular Heartbeat"}),
        ("2026-11-20T10:57:11", "job_result", {"job_name": "symptom_inject", "success": True}),
        ("2026-11-20T10:58:00", "bt_disconnect_not_supported", {}),
        ("2026-11-20T11:00:46", "airplane_mode_done", {"minutes": 2}),
        ("2026-11-20T11:01:37", "bluetooth_reconnected", {"elapsed_sec": 174}),
        ("2026-11-20T12:55:09", "capture_logs_success", {"zip_mb": 10.8}),
    ])
    _run(tmp, "regression", [
        ("2026-11-19T17:02:07", "regression_suite_result", {"suite": "login", "passed": 7, "total": 7, "failures": []}),
        ("2026-11-20T13:09:00", "regression_suite_result", {"suite": "diary", "passed": 8, "total": 9, "failures": ["TC-DIARY-006: not saved"]}),
    ])
    _run(tmp, "20261101_090000", [("2026-11-01T09:00:00", "run_start", {}),
                                  ("2026-11-01T09:01:00", "regression_suite_result", {"suite": "main", "passed": 1, "total": 7, "failures": []})])


def test_regression_takes_latest_non_skipped_per_suite_in_range(tmp_path):
    _fixture(tmp_path)
    reg = regression(load_runs(tmp_path, since="2026-11-19"), since="2026-11-19")
    assert set(reg) == {"login", "diary"}
    assert reg["login"]["passed"] == 7 and reg["diary"]["failures"] == ["TC-DIARY-006: not saved"]


def test_expand_fills_tables_and_tiles(tmp_path):
    _fixture(tmp_path)
    rep = {"title": {"ko": "결과", "en": "Results"}, "tiles": [{"n": "auto:regression"}, {"n": "auto:symptoms"}],
           "sections": [{"type": "auto_regression"}, {"type": "auto_longrun"}]}
    out = expand(rep, tmp_path, since="2026-11-19")
    assert out["tiles"][0]["n"] == "15/16" and out["tiles"][1]["n"] == "1/1"
    en = render(out, {}, "en", "x")
    assert "Step 1 · MC ID / PIN input" in en and "TC-DIARY-006: not saved" in en
    assert "Airplane 1/1" in en and "auto reconnect 174 s" in en and "BT not possible" in en and "10.8MB" in en
    assert "No end record" in en
    ko = render(out, {}, "ko", "x")
    assert "비행기 1/1" in ko and "자동 재연결 174초" in ko


def test_empty_period_says_so(tmp_path):
    _fixture(tmp_path)
    out = expand({"title": "t", "sections": [{"type": "auto_regression"}, {"type": "auto_longrun"}]}, tmp_path, since="2026-12-01")
    en = render(out, {}, "en", "x")
    assert "No regression results in this period" in en and "No long runs in this period" in en


def test_run_regression_logs_suite_result():
    from src.run_regression import _log_suite_result
    got = []
    rep = SimpleNamespace(log_event=lambda e, d: got.append((e, d)))
    R = lambda n, p, s=False, m="": SimpleNamespace(name=n, passed=p, skipped=s, message=m, inconclusive=False)
    _log_suite_result(rep, "diary", [R("TC-DIARY-001 | a", True), R("TC-DIARY-006 | b", False, m="not saved"),
                                     R("TC-DIARY-007 | c", True, True, "BT")])
    ev, d = got[0]
    assert ev == "regression_suite_result" and d["suite"] == "diary"
    assert (d["passed"], d["total"]) == (1, 2) and d["failures"] == ["TC-DIARY-006: not saved"]
    assert d["skipped_tests"] == ["TC-DIARY-007: BT"]


def test_dashboard_builds_and_serves_share_report(tmp_path, monkeypatch):
    import web.app as app_mod
    data, out, runs = tmp_path / "data", tmp_path / "share", tmp_path / "runs"
    data.mkdir()
    _fixture(runs)
    (data / "auto_recent.json").write_text(json.dumps(
        {"title": {"ko": "결과", "en": "Results"}, "since": "2026-11-19", "sections": [{"type": "auto_regression"}]}))
    (data / "x_results.json").write_text("{}")
    monkeypatch.setattr(app_mod, "SHARE_DATA_DIR", data)
    monkeypatch.setattr(app_mod, "SHARE_OUT_DIR", out)
    monkeypatch.setattr(app_mod, "ROOT", tmp_path.parent)          # not used for runs below
    import share_report.build as b
    real = b.build
    monkeypatch.setattr(b, "build", lambda p, **kw: real(p, **{**kw, "runs_dir": str(runs), "pdf": False}))
    c = app_mod.app.test_client()
    assert c.get("/api/share-report/files").get_json()["files"] == ["auto_recent.json"]
    r = c.post("/api/share-report", json={"file": "auto_recent.json"}).get_json()
    assert r["ok"] and len(r["files"]) == 2 and not r["pdf"]
    page = c.get("/share/" + r["files"][1])
    assert page.status_code == 200 and b"Regression tests" in page.data
    assert c.get("/share/../x_results.json").status_code == 404
    assert c.post("/api/share-report", json={"file": "nope.json"}).status_code == 400
