"""
Regression tests for review 2026-11-12 (BT-off / airplane-mode tests,
Android). Ported from MA-automation, where the same code was fixed in
reviews 2026-11-05 and 2026-11-11:

1. Stopping the run mid-window must put BT / airplane mode back, both from
   the workflow itself (stop_event) and from the run-end ADB backstop.
2. A BT cycle whose re-enable can't be confirmed is a failure, not a
   bt_disconnect_done.
3. BT and airplane each keep their own interval.

Airplane mode: a phone that keeps BT off after airplane
mode turns off must still end with BT on (stop or not), and an airplane
mode that never turned on is a failure, not airplane_mode_done.

Run: .venv/bin/pytest tests/test_connectivity_tests_review_2026_11_12.py -v
"""
import threading
import types

from src.main import _run_periodic_tests
from src.workflows import airplane_mode, bt_disconnect, conn_restore


class _Reporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data=None):
        self.events.append((name, data or {}))

    def names(self):
        return [e[0] for e in self.events]


class _FakePhone:
    """Stands in for `adb shell` — tracks BT / airplane settings."""

    def __init__(self, bt_enable_works=True, airplane_kills_bt=False, airplane_applies=True,
                 bt_read_fails=False):
        self.bt_on = "1"
        self.airplane_on = "0"
        self.bt_enable_works = bt_enable_works
        # Real phones: airplane mode takes BT down, and some don't bring it
        # back when airplane mode turns off.
        self.airplane_kills_bt = airplane_kills_bt
        # False: the command exits 0 but the setting never changes.
        self.airplane_applies = airplane_applies
        # True: reading bluetooth_on gives an empty answer (adb hiccup).
        self.bt_read_fails = bt_read_fails
        self.cmds = []

    def run(self, cmd, **kw):
        args = cmd[cmd.index("shell") + 1:]
        self.cmds.append(" ".join(args))
        out = ""
        if args[:3] == ["settings", "get", "global"]:
            out = {"bluetooth_on": "" if self.bt_read_fails else self.bt_on,
                   "airplane_mode_on": self.airplane_on}[args[3]]
        elif args[-1] == "disable" and "bluetooth" in " ".join(args):
            self.bt_on = "0"
        elif args[-1] == "enable" and "bluetooth" in " ".join(args):
            if self.bt_enable_works:
                self.bt_on = "1"
        elif args[:3] == ["cmd", "connectivity", "airplane-mode"]:
            if self.airplane_applies:
                self.airplane_on = "1" if args[3] == "enable" else "0"
                if args[3] == "enable" and self.airplane_kills_bt:
                    self.bt_on = "0"
        return types.SimpleNamespace(returncode=0, stdout=out if kw.get("text") else out.encode(),
                                     stderr="" if kw.get("text") else b"")


def _driver():
    d = types.SimpleNamespace(cfg={"udid": "SERIAL1"}, reporter=_Reporter(), checks=0)

    def check_connectivity():
        d.checks += 1
    d.check_connectivity = check_connectivity
    d.ensure_session = d.ensure_ui_automation = d.reconnect = lambda: None
    d.wait_for_adb_device = lambda timeout=0: False
    return d


def _patch(monkeypatch, phone):
    for mod in (bt_disconnect, airplane_mode, conn_restore):
        monkeypatch.setattr(mod.subprocess, "run", phone.run)
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)


# ── 1. stop mid-window ───────────────────────────────────────────────────────

def test_bt_test_stopped_mid_window_turns_bt_back_on(monkeypatch):
    phone, d = _FakePhone(), _driver()
    _patch(monkeypatch, phone)
    stop = threading.Event()
    stop.set()  # Stop pressed while BT is off

    bt_disconnect.run_bt_disconnect(d, 10, stop_event=stop)

    assert phone.bt_on == "1"
    assert "bt_disconnect_aborted" in d.reporter.names()
    assert "bt_disconnect_done" not in d.reporter.names()
    assert d.checks == 1  # only the post-disable check, no post-reconnect UI check
    assert conn_restore.pending(d) == set()


def test_airplane_test_stopped_mid_window_turns_airplane_off(monkeypatch):
    phone, d = _FakePhone(), _driver()
    _patch(monkeypatch, phone)
    stop = threading.Event()
    stop.set()

    airplane_mode.run_airplane_mode(d, 5, stop_event=stop)

    assert phone.airplane_on == "0"
    assert "airplane_mode_aborted" in d.reporter.names()
    assert "airplane_mode_done" not in d.reporter.names()
    assert conn_restore.pending(d) == set()


def test_run_end_backstop_restores_what_the_thread_left_off(monkeypatch):
    """Thread killed before it could restore (e.g. hung past the join)."""
    phone, d = _FakePhone(), _driver()
    _patch(monkeypatch, phone)
    phone.bt_on, phone.airplane_on = "0", "1"
    conn_restore.pending(d).update({"bt", "airplane"})

    conn_restore.restore_connectivity(d, d.reporter)

    assert (phone.airplane_on, phone.bt_on) == ("0", "1")
    assert ("connectivity_restore_on_exit",
            {"pending": ["airplane", "bt"], "failed": []}) in d.reporter.events


def test_run_end_backstop_noop_when_nothing_pending(monkeypatch):
    phone, d = _FakePhone(), _driver()
    _patch(monkeypatch, phone)

    conn_restore.restore_connectivity(d, d.reporter)

    assert phone.cmds == [] and d.reporter.events == []


# ── 2. BT restore failure is a failure ───────────────────────────────────────

def test_bt_not_restored_is_failed_not_done(monkeypatch):
    phone, d = _FakePhone(bt_enable_works=False), _driver()
    _patch(monkeypatch, phone)
    monkeypatch.setattr(bt_disconnect, "_wall_sleep", lambda *a, **k: False)

    bt_disconnect.run_bt_disconnect(d, 10)

    names = d.reporter.names()
    assert "bt_disconnect_done" not in names
    failed = [e[1] for e in d.reporter.events if e[0] == "bt_disconnect_failed"]
    assert failed and failed[0]["phase"] == "restore"
    assert "bt" in conn_restore.pending(d)  # left for the run-end backstop


def test_bt_restored_is_done(monkeypatch):
    phone, d = _FakePhone(), _driver()
    _patch(monkeypatch, phone)
    monkeypatch.setattr(bt_disconnect, "_wall_sleep", lambda *a, **k: False)

    bt_disconnect.run_bt_disconnect(d, 10)

    assert "bt_disconnect_done" in d.reporter.names()
    assert "bt_disconnect_failed" not in d.reporter.names()


# ── review 2026-11-11: airplane mode and BT ─────────────────────────────────

def test_airplane_stopped_on_phone_that_keeps_bt_off(monkeypatch):
    """Stop mid-window on a phone where airplane off doesn't bring BT back:
    the workflow (or, failing that, the run-end restore) must turn BT on."""
    phone, d = _FakePhone(airplane_kills_bt=True), _driver()
    _patch(monkeypatch, phone)
    stop = threading.Event()
    stop.set()

    airplane_mode.run_airplane_mode(d, 5, stop_event=stop)
    conn_restore.restore_connectivity(d, d.reporter)

    assert (phone.airplane_on, phone.bt_on) == ("0", "1")
    assert "airplane_mode_aborted" in d.reporter.names()
    assert conn_restore.pending(d) == set()


def test_airplane_bt_not_restored_is_failed_and_left_for_backstop(monkeypatch):
    phone, d = _FakePhone(airplane_kills_bt=True, bt_enable_works=False), _driver()
    _patch(monkeypatch, phone)
    monkeypatch.setattr(airplane_mode, "_wall_sleep", lambda *a, **k: False)

    airplane_mode.run_airplane_mode(d, 5)

    assert "airplane_mode_done" not in d.reporter.names()
    failed = [e[1] for e in d.reporter.events if e[0] == "airplane_mode_failed"]
    assert failed and failed[0]["phase"] == "restore"
    assert conn_restore.pending(d) == {"bt"}


def test_airplane_bt_comes_back_after_reenable_is_done(monkeypatch):
    phone, d = _FakePhone(airplane_kills_bt=True), _driver()
    _patch(monkeypatch, phone)
    monkeypatch.setattr(airplane_mode, "_wall_sleep", lambda *a, **k: False)

    airplane_mode.run_airplane_mode(d, 5)

    assert phone.bt_on == "1"
    assert "airplane_mode_done" in d.reporter.names()
    assert conn_restore.pending(d) == set()


def test_airplane_bt_unreadable_is_not_taken_as_on(monkeypatch):
    """An empty bluetooth_on read must not count as BT on (MA hit this in
    a `!= "0"` check), or BT stays off with nothing left pending."""
    phone, d = _FakePhone(airplane_kills_bt=True, bt_read_fails=True), _driver()
    _patch(monkeypatch, phone)
    monkeypatch.setattr(airplane_mode, "_wall_sleep", lambda *a, **k: False)

    airplane_mode.run_airplane_mode(d, 5)

    assert "airplane_mode_done" not in d.reporter.names()
    assert any("bluetooth enable" in c for c in phone.cmds)  # tried to turn it on
    assert "bt" in conn_restore.pending(d)


def test_airplane_that_never_turned_on_is_failed_not_done(monkeypatch):
    phone, d = _FakePhone(airplane_applies=False), _driver()
    _patch(monkeypatch, phone)
    waited = []
    monkeypatch.setattr(airplane_mode, "_wall_sleep", lambda *a, **k: waited.append(1))

    airplane_mode.run_airplane_mode(d, 5)

    assert "airplane_mode_done" not in d.reporter.names()
    failed = [e[1] for e in d.reporter.events if e[0] == "airplane_mode_failed"]
    assert failed and failed[0]["phase"] == "enable"
    assert waited == []  # didn't sit out the window with the radios up
    assert conn_restore.pending(d) == set()


# ── 3. separate intervals ────────────────────────────────────────────────────

class _Clock:
    """Fake wall clock; stop.wait() advances it instead of sleeping."""

    def __init__(self, stop_after_h):
        self.t = 0.0
        self.end = stop_after_h * 3600

    def __call__(self):
        return self.t


class _Stop:
    def __init__(self, clock):
        self.clock = clock

    def is_set(self):
        return self.clock.t >= self.clock.end

    def wait(self, sec):
        self.clock.t += sec
        return self.is_set()


def test_bt_and_airplane_keep_their_own_interval():
    clock = _Clock(stop_after_h=6.5)
    runs = []
    tests = [(1, lambda: runs.append(("bt", clock.t))),
             (3, lambda: runs.append(("ap", clock.t)))]

    _run_periodic_tests(tests, _Stop(clock), clock=clock)

    bt = [t for n, t in runs if n == "bt"]
    ap = [t for n, t in runs if n == "ap"]
    assert len(bt) == 7          # 0h,1h,…,6h
    assert len(ap) == 3          # 0h,3h,6h — not every BT cycle
    # start-to-start: a test's own runtime/gap doesn't push the next one out
    assert all(abs(b - i * 3600) <= 120 for i, b in enumerate(bt))


def test_single_test_enabled():
    clock = _Clock(stop_after_h=2.5)
    runs = []

    _run_periodic_tests([(1, lambda: runs.append(clock.t))], _Stop(clock), clock=clock)

    assert len(runs) == 3
