"""
Regression tests for _is_allowed_app_log_path() (web/app.py) -- the
/app_logs/<path> download route must only ever serve *.zip captures,
not any other file under output/.

Review finding, 2026-08-18: the route allowed the whole of output/ as
a serve root, not just output/<run_id>/app_logs/. This server binds to
all interfaces (app.run(host="::", ...), the "Share on local network"
URL shown at startup) -- anyone on the same LAN could otherwise
browse/download any run's screenshots, events.jsonl, or summary.html
by guessing a path, not just app-log zips.

Run: .venv/bin/pytest tests/test_app_log_serve_scope.py -v
"""
from pathlib import Path

import web.app as app_mod


def _set_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod, "_APP_LOGS_STANDALONE_ROOT", (tmp_path / "artifacts" / "app_logs_captures").resolve())
    monkeypatch.setattr(app_mod, "_APP_LOGS_OUTPUT_ROOT", (tmp_path / "output").resolve())


def test_allows_run_end_auto_capture_zip(tmp_path, monkeypatch):
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "output" / "20260818_133234" / "app_logs" / "abc-123.zip"
    assert app_mod._is_allowed_app_log_path(p) is True


def test_allows_mid_run_manual_capture_zip_with_timestamp_subfolder(tmp_path, monkeypatch):
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "output" / "20260818_133234" / "app_logs" / "20260818_140000" / "abc-123.zip"
    assert app_mod._is_allowed_app_log_path(p) is True


def test_allows_standalone_capture_zip(tmp_path, monkeypatch):
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "artifacts" / "app_logs_captures" / "20260818_140000" / "abc-123.zip"
    assert app_mod._is_allowed_app_log_path(p) is True


def test_rejects_events_jsonl_under_a_run_dir(tmp_path, monkeypatch):
    """The exact real gap: any other file under output/<run_id>/ used
    to be servable, not just its app_logs/ subtree."""
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "output" / "20260818_133234" / "events.jsonl"
    assert app_mod._is_allowed_app_log_path(p) is False


def test_rejects_screenshot_under_a_run_dir(tmp_path, monkeypatch):
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "output" / "20260818_133234" / "screenshots" / "open_menu_failed.png"
    assert app_mod._is_allowed_app_log_path(p) is False


def test_rejects_summary_html(tmp_path, monkeypatch):
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "output" / "20260818_133234" / "summary.html"
    assert app_mod._is_allowed_app_log_path(p) is False


def test_rejects_non_zip_inside_app_logs_dir(tmp_path, monkeypatch):
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "output" / "20260818_133234" / "app_logs" / "notes.txt"
    assert app_mod._is_allowed_app_log_path(p) is False


def test_rejects_path_outside_both_roots(tmp_path, monkeypatch):
    _set_roots(monkeypatch, tmp_path)
    p = tmp_path / "config" / "accurkardia.yaml"
    assert app_mod._is_allowed_app_log_path(p) is False
