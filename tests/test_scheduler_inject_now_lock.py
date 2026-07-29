"""
Issue #29: Inject Now used to be able to run concurrently with a regular
scheduled job (both call _run_with_health_check, and nothing serialized
them — driver._job_busy only pauses the connectivity monitor, it was never
a mutex between job invocations). Fixed with a threading.Lock() in
LongRunScheduler._run_interval().

This drives the real scheduler (not a mock of the lock itself) with a slow
fake job and a real Inject Now trigger timed to land while the first job
is still running, and asserts the two never overlap.

Run: .venv/bin/pytest tests/test_scheduler_inject_now_lock.py -v
Takes ~20s (real wall-clock time — the scheduler is driven for real).
"""
import threading
import time

from src.scheduler import LongRunScheduler


class _FakeReporter:
    def log_event(self, *a, **k):
        pass


def test_inject_now_does_not_overlap_regular_job(tmp_path, monkeypatch):
    import src.scheduler as scheduler_mod

    # Safety: redirect the inject-now flag file to an isolated temp path.
    # The module-level constant is what _inject_now_watcher polls, so this
    # must never point at the real runtime/inject_now.json — a live run's
    # own watcher process could otherwise pick up a stray trigger from
    # this test and fire an unplanned real injection.
    tmp_inject_file = tmp_path / "inject_now.json"
    monkeypatch.setattr(scheduler_mod, "_INJECT_NOW_FILE", tmp_inject_file)

    events = []
    lock_check = threading.Lock()
    active_count = [0]
    max_concurrent = [0]

    def job_callable(at_hour=None, payload=None):
        with lock_check:
            active_count[0] += 1
            max_concurrent[0] = max(max_concurrent[0], active_count[0])
        events.append(("enter", time.time()))
        time.sleep(1.5)  # hold the "session" long enough for a real overlap to show up if unlocked
        events.append(("exit", time.time()))
        with lock_check:
            active_count[0] -= 1

    scheduler = LongRunScheduler(
        duration_hours=15 / 3600,  # ~15s total run
        interval_hours=100,        # never fires on its own within the run — only start_immediately + Inject Now do
        start_immediately=True,
        plan=[],
        catalog=[],
        reporter=_FakeReporter(),
        jitter_seconds=0,
        quiet_hours={},
        recovery_cfg={},
    )

    def trigger_inject_now():
        # _inject_now_watcher polls every 5s — the trigger file must exist
        # BEFORE its first poll tick (t=5s) to be picked up on that check,
        # landing the actual job execution around t=6s (tick + its own 1s
        # run_date offset), while the first job (running t=5..6.5) is still
        # active. Writing it any later (e.g. t=5.3s) misses that first poll
        # entirely — the watcher wouldn't see it until t=10s, by which point
        # the first job has long since finished and nothing could ever
        # overlap regardless of whether job_lock works. (Confirmed by
        # deliberately breaking job_lock during development: with a t=5.3s
        # trigger the test kept passing even with no lock at all; with this
        # t=0.5s trigger, breaking job_lock reliably reproduces a real
        # overlap — max_concurrent=2, e.g. enter@5.0/6.0, exit@6.5/7.5.)
        time.sleep(0.5)
        tmp_inject_file.write_text("{}")

    threading.Thread(target=trigger_inject_now, daemon=True).start()

    scheduler.run(job_callable, driver=None)

    assert len(events) == 4, f"expected 2 jobs (regular + inject-now) to run, got {events}"
    assert max_concurrent[0] <= 1, (
        f"RACE DETECTED: max_concurrent={max_concurrent[0]} — "
        "the regular job and Inject Now ran at the same time, job_lock did not serialize them"
    )

    # The second job's "enter" must be at/after the first job's "exit" —
    # not just "never simultaneously active" (which max_concurrent already
    # checks) but genuinely serialized in time.
    (_, enter1), (_, exit1), (_, enter2), (_, exit2) = events
    assert enter1 < exit1 <= enter2 < exit2, f"jobs did not run in serialized order: {events}"
