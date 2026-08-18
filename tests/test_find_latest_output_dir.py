"""
Regression tests for find_latest_output_dir() (web/app.py) matching a
run's own output directory by NAME (creation timestamp baked into
main.py/main_ios.py's own dir naming) instead of filesystem mtime.

Real race caught live (2026-08-18): three rapid run restarts ~70s
apart. The old mtime-based matching (`mtime >= since - 1`) picked up a
DIFFERENT, still-finishing previous run's directory instead of the new
run's own -- that previous run's own cleanup (capture_logs, writing
summary.html) touched its directory's mtime within the new run's 1s
grace window. Once wrongly set, the dashboard stayed stuck showing the
wrong run's data for the rest of the session (callers only re-look-up
`if not out_dir`, never re-validate an already-set one).

Run: .venv/bin/pytest tests/test_find_latest_output_dir.py -v
"""
import datetime
import os

import web.app as app_mod


def _mkdir_named_at(out_root, dt: datetime.datetime):
    d = out_root / dt.strftime("%Y%m%d_%H%M%S")
    d.mkdir()
    return d


def test_finds_the_dir_created_for_this_run(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    out_root = tmp_path / "output"
    out_root.mkdir()

    since = datetime.datetime(2026, 8, 18, 13, 32, 34).timestamp()
    this_run_dir = _mkdir_named_at(out_root, datetime.datetime(2026, 8, 18, 13, 32, 34))

    found = app_mod.find_latest_output_dir(since)
    assert found == str(this_run_dir)


def test_ignores_a_previous_runs_dir_touched_by_its_own_cleanup(tmp_path, monkeypatch):
    """The exact real bug: an older run's directory (named well before
    `since`) gets its mtime bumped by its own finishing cleanup right as
    the new run starts -- must not be picked over the new run's own
    (later-named) directory.

    Uses os.utime() to control mtimes explicitly and a `since` anchored
    to a fixed point in time, rather than real wall-clock "now" -- the
    old mtime-based code's `mtime >= since - 1` filter only misbehaves
    when mtimes sit within ~1s of `since`, so the test has to place them
    there deliberately instead of relying on however fast tmp_path
    directory creation happens to run in practice.
    """
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    out_root = tmp_path / "output"
    out_root.mkdir()

    since = datetime.datetime(2026, 8, 18, 13, 32, 34).timestamp()

    prev_run_dir = _mkdir_named_at(out_root, datetime.datetime(2026, 8, 18, 13, 31, 22))
    # Simulate the previous run's own run-end cleanup writing to its
    # directory right as the new run starts -- bumps mtime to land
    # inside the old code's 1s grace window relative to `since`.
    (prev_run_dir / "events.jsonl").write_text("late write\n")
    os.utime(prev_run_dir, (since - 0.5, since - 0.5))

    this_run_dir = _mkdir_named_at(out_root, datetime.datetime(2026, 8, 18, 13, 32, 34))
    os.utime(this_run_dir, (since - 5, since - 5))  # created moments before mtime is checked

    found = app_mod.find_latest_output_dir(since)
    assert found == str(this_run_dir)
    assert found != str(prev_run_dir)


def test_ignores_non_run_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    out_root = tmp_path / "output"
    out_root.mkdir()
    (out_root / "regression").mkdir()
    (out_root / "tmp").mkdir()

    since = datetime.datetime(2026, 8, 18, 13, 32, 34).timestamp()
    this_run_dir = _mkdir_named_at(out_root, datetime.datetime(2026, 8, 18, 13, 32, 34))

    assert app_mod.find_latest_output_dir(since) == str(this_run_dir)


def test_returns_none_when_nothing_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    out_root = tmp_path / "output"
    out_root.mkdir()
    since = datetime.datetime(2026, 8, 18, 13, 32, 34).timestamp()
    assert app_mod.find_latest_output_dir(since) is None
