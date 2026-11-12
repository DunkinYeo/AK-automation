"""
Regression test: the persisted run-state file (runtime/web_run_state.json)
must only be deleted when the run's process is really gone.

Caught live 2026-11-11 (MA, run 20261111_140617): a review tool imported
web.app in a sandbox where `ps` couldn't run. The import-time re-attach
check failed closed and deleted the live run's state file, so the next
dashboard restart never re-attached and the dashboard showed no run while
the run kept going for a day.

Run: .venv/bin/pytest tests/test_run_state_kept_when_unverified.py -v
"""
import ast
import json
import os
from pathlib import Path

import web.app as app_mod

ROOT = Path(__file__).resolve().parent.parent


def _state_file(tmp_path, monkeypatch, pid):
    f = tmp_path / "web_run_state.json"
    f.write_text(json.dumps({"pid": pid, "start_ts": 1.0, "out_dir": None}))
    monkeypatch.setattr(app_mod, "_RUN_STATE_FILE", f)
    monkeypatch.setattr(app_mod, "_state", dict(app_mod._state, pid=None, start_ts=None))
    return f


def test_import_does_not_run_the_reattach_check():
    """The loader may delete the file, so it must only run when the server
    starts (main()), never on a plain `import web.app`."""
    tree = ast.parse((ROOT / "web" / "app.py").read_text())
    top_level_calls = [
        n.value.func.id for n in tree.body
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
    ]
    assert "_load_persisted_run" not in top_level_calls
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert "_load_persisted_run()" in ast.unparse(main)


def test_unverifiable_live_pid_keeps_the_file(tmp_path, monkeypatch):
    f = _state_file(tmp_path, monkeypatch, os.getpid())
    monkeypatch.setattr(app_mod, "_pid_is_our_run", lambda pid: False)  # `ps` failed

    app_mod._load_persisted_run()

    assert f.exists()
    assert app_mod._state["pid"] is None  # not re-attached either


def test_dead_pid_still_clears_the_file(tmp_path, monkeypatch):
    f = _state_file(tmp_path, monkeypatch, 999999)
    monkeypatch.setattr(app_mod, "_pid_alive", lambda pid: False)

    app_mod._load_persisted_run()

    assert not f.exists()


def test_status_poll_keeps_file_when_check_is_inconclusive(tmp_path, monkeypatch):
    f = _state_file(tmp_path, monkeypatch, os.getpid())
    app_mod._state.update(pid=os.getpid(), proc=None, stopping=False, out_dir=None, start_ts=None)
    monkeypatch.setattr(app_mod, "_pid_is_our_run", lambda pid: False)
    monkeypatch.setattr(app_mod, "appium_ok", lambda: True)

    with app_mod.app.test_client() as c:
        c.get("/api/status")

    assert f.exists()
    assert app_mod._state["pid"] == os.getpid()
