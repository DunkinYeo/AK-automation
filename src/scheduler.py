"""
Long-run scheduler.

Drift prevention strategy:
- plan mode  : each job is a one-shot `date` trigger at an absolute wall-clock time.
- interval mode: after every successful execution, the *next* job is re-registered
  as a new `date` trigger (start_time + N * interval). This avoids APScheduler
  interval drift caused by execution time or system sleep.

Pre-job health checks (in order):
  1. Appium session alive     — driver.ensure_session()
  2. App brought to foreground — driver.bring_to_foreground()
  3. UI health assert          — driver.assert_ui_health()
     (checks that the measurement screen is unobstructed)
Any check failure triggers 3-step escalating recovery before the job runs.
"""

import dataclasses
import datetime
import json
import logging
import random
import time
from pathlib import Path

_OVERRIDE_FILE    = Path(__file__).resolve().parent.parent / "runtime" / "interval_override.json"
_INJECT_NOW_FILE  = Path(__file__).resolve().parent.parent / "runtime" / "inject_now.json"

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler


def _make_scheduler(cls):
    """
    Create an APScheduler instance, surviving hosts without a usable local
    timezone database. On Windows, Python's zoneinfo has no system tz data —
    without the `tzdata` pip package APScheduler's local-timezone lookup dies
    with "No time zone found with key <tz>" (tester-reported: America/Chicago)
    and the whole run crashes at startup. Fall back to UTC so the run
    continues (quiet-hours then use UTC — degraded but alive).
    """
    try:
        return cls()
    except Exception as e:
        if "No time zone found" not in str(e):
            raise
        import pytz  # APScheduler 3.x hard dependency; ships its own tz data
        logging.getLogger(__name__).warning(
            "Local timezone unavailable (%s) — scheduler falling back to UTC. "
            "Fix permanently with: pip install tzdata", e)
        return cls(timezone=pytz.utc)


# ------------------------------------------------------------------
# Job result
# ------------------------------------------------------------------

@dataclasses.dataclass
class JobResult:
    """Structured outcome returned (and logged) for every scheduled job."""
    job_name: str
    success: bool
    start_ts: str
    end_ts: str = ""
    attempt: int = 1
    reason: str = ""
    artifact_paths: list = dataclasses.field(default_factory=list)


# ------------------------------------------------------------------
# Scheduler
# ------------------------------------------------------------------

class LongRunScheduler:
    def __init__(
        self,
        duration_hours: int,
        interval_hours: float,
        start_immediately: bool,
        plan: list,
        catalog: list,
        reporter,
        jitter_seconds: float = 0,
        quiet_hours: dict = None,
        recovery_cfg: dict = None,
    ):
        self.duration_hours = duration_hours
        self.interval_hours = interval_hours
        self.start_immediately = start_immediately
        self.plan = plan
        self.catalog = catalog
        self.reporter = reporter
        self.jitter_seconds = float(jitter_seconds or 0)
        self.quiet_hours = quiet_hours or {}
        self.recovery_cfg = recovery_cfg or {}

    def run(self, job_callable, driver=None):
        """
        Block until the run duration has elapsed.

        Args:
            job_callable: called with (at_hour, payload) kwargs.
            driver: AndroidDriver instance (optional) used for session health checks.
        """
        start = datetime.datetime.now()
        end = start + datetime.timedelta(hours=self.duration_hours)

        if self.plan:
            self._run_plan(job_callable, driver, start, end)
        else:
            self._run_interval(job_callable, driver, start, end)

    # ------------------------------------------------------------------
    # Plan mode — absolute time offsets
    # ------------------------------------------------------------------

    def _run_plan(self, job_callable, driver, start, end):
        self.reporter.log_event(
            "scheduler_started",
            {
                "mode": "plan",
                "duration_hours": self.duration_hours,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "jitter_seconds": self.jitter_seconds,
                "quiet_hours": self.quiet_hours,
                "warning": "PC must remain powered on and awake; disable sleep/suspend/hibernation",
            },
        )

        sched = _make_scheduler(BlockingScheduler)
        cooldown = int(self.recovery_cfg.get("cooldown_seconds_between_steps", 30))
        # Allow missed jobs to fire for up to 1 hour after their scheduled time
        # so that a brief Mac sleep does not silently skip an injection.
        grace = int(self.interval_hours * 3600) if self.interval_hours else 3600

        for item in self.plan:
            at = float(item.get("at_hour", 0))
            jitter = random.uniform(-self.jitter_seconds, self.jitter_seconds) if self.jitter_seconds else 0
            when = start + datetime.timedelta(hours=at) + datetime.timedelta(seconds=jitter)

            if when > end:
                continue

            if _is_quiet_hour(when, self.quiet_hours):
                self.reporter.log_event(
                    "job_skipped_quiet_hours",
                    {"at_hour": at, "run_at": when.isoformat(), "quiet_hours": self.quiet_hours},
                )
                continue

            payload = {
                "symptoms": item.get("symptoms"),
                "other_text": item.get("other_text", ""),
                "activities": item.get("activities") or [],
            }
            self.reporter.log_event(
                "schedule_add",
                {"type": "plan", "at_hour": at, "run_at": when.isoformat(), "jitter_sec": round(jitter, 1)},
            )

            def _make_job(at_h, p, cd):
                def _job():
                    _run_with_health_check(job_callable, driver, at_h, p, self.reporter, cd)
                return _job

            sched.add_job(_make_job(at, payload, cooldown), "date", run_date=when, misfire_grace_time=grace)

        sched.add_job(lambda: sched.shutdown(wait=False), "date", run_date=end)
        sched.start()

    # ------------------------------------------------------------------
    # Interval mode — drift-free re-registration
    # ------------------------------------------------------------------

    def _run_interval(self, job_callable, driver, start, end):
        sched = _make_scheduler(BackgroundScheduler)
        counter = [0]
        cooldown = int(self.recovery_cfg.get("cooldown_seconds_between_steps", 30))
        # Grace time = full run duration so that jobs missed during a host sleep/wake
        # cycle are still executed when the machine wakes up, rather than being dropped.
        grace = int(self.duration_hours * 3600)

        def _schedule_next():
            # Check for mid-test interval override from web UI
            override_h = None
            try:
                if _OVERRIDE_FILE.exists():
                    override_h = float(json.loads(_OVERRIDE_FILE.read_text()).get("interval_hours", 0)) or None
            except Exception:
                pass

            now = datetime.datetime.now()
            jitter = random.uniform(-self.jitter_seconds, self.jitter_seconds) if self.jitter_seconds else 0
            if override_h:
                # Schedule relative to now using the new interval
                counter[0] += 1
                next_run = now + datetime.timedelta(hours=override_h) + datetime.timedelta(seconds=jitter)
                if next_run >= end:
                    return
            else:
                # Advance the counter past any slots already in the past to avoid
                # a burst of back-to-back injections after a long host sleep.
                while True:
                    counter[0] += 1
                    offset_hours = counter[0] * self.interval_hours
                    next_run = start + datetime.timedelta(hours=offset_hours) + datetime.timedelta(seconds=jitter)
                    if next_run >= end:
                        return
                    if next_run > now:
                        break
                    self.reporter.log_event("job_skipped_host_sleep", {
                        "index": counter[0], "scheduled": next_run.isoformat(),
                    })

            self.reporter.log_event(
                "schedule_add",
                {
                    "type": "interval",
                    "index": counter[0],
                    "run_at": next_run.isoformat(),
                    "jitter_sec": round(jitter, 1),
                },
            )

            def _job():
                # Check quiet hours at run time (interval jobs are chained dynamically)
                try:
                    if _is_quiet_hour(datetime.datetime.now(), self.quiet_hours):
                        self.reporter.log_event(
                            "job_skipped_quiet_hours",
                            {"index": counter[0], "quiet_hours": self.quiet_hours},
                        )
                    else:
                        _run_with_health_check(job_callable, driver, None, None, self.reporter, cooldown)
                except Exception:
                    pass
                finally:
                    _schedule_next()

            sched.add_job(_job, "date", run_date=next_run, misfire_grace_time=grace)

        self.reporter.log_event(
            "scheduler_started",
            {
                "mode": "interval",
                "duration_hours": self.duration_hours,
                "interval_hours": self.interval_hours,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "jitter_seconds": self.jitter_seconds,
                "quiet_hours": self.quiet_hours,
                "warning": "PC must remain powered on and awake; disable sleep/suspend/hibernation",
            },
        )

        if self.start_immediately:
            first_run = datetime.datetime.now() + datetime.timedelta(seconds=5)
            self.reporter.log_event(
                "schedule_add",
                {"type": "interval_immediate", "run_at": first_run.isoformat()},
            )

            def _first_job():
                try:
                    _run_with_health_check(job_callable, driver, None, None, self.reporter, cooldown)
                except Exception:
                    pass
                finally:
                    _schedule_next()

            sched.add_job(_first_job, "date", run_date=first_run, misfire_grace_time=grace)
        else:
            _schedule_next()

        sched.start()

        def _inject_now_watcher():
            import threading as _t
            while datetime.datetime.now() < end:
                time.sleep(5)
                try:
                    if _INJECT_NOW_FILE.exists():
                        _INJECT_NOW_FILE.unlink()
                        self.reporter.log_event("inject_now_triggered", {})
                        sched.add_job(
                            lambda: _run_with_health_check(job_callable, driver, None, None, self.reporter, cooldown),
                            "date",
                            run_date=datetime.datetime.now() + datetime.timedelta(seconds=1),
                            misfire_grace_time=grace,
                        )
                except Exception:
                    pass

        import threading as _th
        _th.Thread(target=_inject_now_watcher, daemon=True).start()

        while datetime.datetime.now() < end:
            time.sleep(10)

        sched.shutdown(wait=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _is_quiet_hour(dt: datetime.datetime, quiet_hours: dict) -> bool:
    """Return True if dt falls within the configured quiet window."""
    if not quiet_hours:
        return False
    start = quiet_hours.get("start")
    end = quiet_hours.get("end")
    if start is None or end is None:
        return False
    h = dt.hour + dt.minute / 60.0
    if start <= end:          # same-day window, e.g. 02:00–06:00
        return start <= h < end
    else:                     # overnight window, e.g. 23:00–06:00
        return h >= start or h < end


def _run_with_health_check(job_callable, driver, at_hour, payload, reporter, cooldown_seconds=30):
    """
    Run pre-job health checks then execute the job.
    Returns a JobResult; also emits job_result event to the reporter.

    Checks (in order):
      1. Appium session alive
      2. Bring app to foreground
      3. UI health assert (measurement screen unobstructed)
    Any failure triggers 3-step escalating recovery with cooldown+recheck.
    """
    start_ts = datetime.datetime.now().isoformat(timespec="seconds")
    result = JobResult(
        job_name="symptom_inject",
        success=False,
        start_ts=start_ts,
    )
    reporter.log_event("job_start", {"at_hour": at_hour, "start_ts": start_ts})

    if driver is not None:
        # 1. Session check
        try:
            driver.ensure_session()
        except Exception as e:
            reporter.log_event("session_check_failed", {"error": str(e)})
            _attempt_recovery(driver, reporter, cooldown_seconds)

        # 2. Bring app to foreground
        try:
            driver.bring_to_foreground()
            driver.wait_idle(1.0)
        except Exception as e:
            reporter.log_event("foreground_failed", {"error": str(e)})
            _attempt_recovery(driver, reporter, cooldown_seconds)

        # 3. UI health check
        try:
            driver.assert_ui_health()
        except Exception as e:
            reporter.log_event("ui_health_check_failed", {"error": str(e)})
            try:
                _attempt_recovery(driver, reporter, cooldown_seconds)
            except RuntimeError as recovery_exc:
                result.success = False
                result.reason = str(recovery_exc)
                result.end_ts = datetime.datetime.now().isoformat(timespec="seconds")
                reporter.log_event("job_failed", {"error": str(recovery_exc), "at_hour": at_hour})
                reporter.log_event("job_result", dataclasses.asdict(result))
                return result

    try:
        job_callable(at_hour=at_hour, payload=payload)
        result.success = True
        result.reason = "ok"
    except Exception as e:
        result.success = False
        result.reason = str(e)
        reporter.log_event("job_failed", {"error": str(e), "at_hour": at_hour})
        raise
    finally:
        result.end_ts = datetime.datetime.now().isoformat(timespec="seconds")
        reporter.log_event("job_result", dataclasses.asdict(result))

    return result


def _is_instrumentation_crash(exc: Exception) -> bool:
    """Return True when the error is a dead UiAutomator2 instrumentation process."""
    msg = str(exc)
    return (
        "instrumentation process is not running" in msg
        or "cannot be proxied to UiAutomator2 server" in msg
    )


def _attempt_recovery(driver, reporter, cooldown_seconds=30):
    """
    3-step escalating recovery with cooldown + UI re-check after each step.

    Step 1: back key + short wait
    Step 2: activate_app (force relaunch)
    Step 3: terminate + activate (kill/relaunch)

    Special case: if UiAutomator2 instrumentation is dead (specific error),
    skip app-level steps and immediately recreate the Appium session.

    After each step: wait cooldown_seconds, then re-check UI health.
    Returns as soon as a step results in a healthy UI.
    """
    for step in [1, 2, 3]:
        reporter.log_event("recovery_step_start", {"step": step})
        try:
            driver.recover_session(step=step)
        except Exception as e:
            reporter.log_event("recovery_step_error", {"step": step, "error": str(e)})

            if _is_instrumentation_crash(e):
                # UiAutomator2 instrumentation process is dead.
                # App-level steps (back key, activate, etc.) cannot work because
                # every Appium command is proxied through the dead instrumentation.
                # Skip remaining steps and recreate the session immediately.
                reporter.log_event("instrumentation_crash_detected", {"step": step})
                try:
                    reporter.log_event("session_recreate_for_instrumentation_crash", {})
                    driver.reconnect()
                    driver.wait_idle(2.0)
                    driver.assert_ui_health()
                    reporter.log_event("post_recreate_ui_health_result", {"healthy": True})
                    return  # recovered
                except Exception as health_exc:
                    reporter.log_event("post_recreate_ui_health_result", {
                        "healthy": False, "error": str(health_exc)
                    })
            else:
                # Non-instrumentation failure — restore session as safety net
                # before proceeding to the next recovery step.
                try:
                    driver.ensure_session()
                except Exception:
                    pass

            continue

        # Wait for app to stabilize before checking
        time.sleep(cooldown_seconds)

        try:
            driver.ensure_session()
            driver.bring_to_foreground()
            driver.wait_idle(2.0)
            driver.assert_ui_health()
            reporter.log_event("recovery_succeeded", {"step": step})
            return  # healthy — done
        except Exception:
            reporter.log_event("recovery_ui_still_unhealthy", {"step": step})
            # Fall through to next step

    reporter.log_event("session_recovery_failed", {"tried_steps": 3})
    raise RuntimeError("Session recovery failed after 3 steps — job aborted")
