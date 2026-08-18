"""
Regression tests for _handle_study_completion_action() (src/driver.py) --
the "On Study Completion" run setting added 2026-08-18: notify (default,
original Slack-only behavior), upload, or skip, chosen per-run in the
web UI since not every run's study data should necessarily be
auto-uploaded (e.g. a synthetic QA study).

Run: .venv/bin/pytest tests/test_study_completion_action.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


class _FakeInnerDriver:
    def __init__(self, page_source=""):
        self.page_source = page_source


def _make_driver(action, upload_percent_after=None, tap_raises=False,
                  skip_confirm_visible=False, success_screen=False):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.reporter = _FakeReporter()
    drv._study_complete_action = action
    drv._slack_webhook = "https://hooks.slack.com/services/fake"
    drv._tap_calls = []
    if success_screen:
        src = "Your study has been completed. Please return the device to the provider."
    elif upload_percent_after is not None:
        src = f'text="Data Upload" text="{upload_percent_after}"'
    else:
        src = ""
    drv.drv = _FakeInnerDriver(page_source=src)

    def _tap_text(text, timeout=5, contains=True):
        drv._tap_calls.append(text)
        if tap_raises:
            raise RuntimeError("tap failed")

    def _is_visible_text(text, timeout=2, contains=True):
        return text == "Yes, Skip" and skip_confirm_visible

    drv.tap_text = _tap_text
    drv.is_visible_text = _is_visible_text
    return drv


def _use_fake_clock(monkeypatch):
    """The upload branch polls with a 300s wall-clock deadline
    (time.time()) between time.sleep(3) calls -- for a case that never
    resolves, a real clock would cost the full 300s per test. Advancing
    a fake clock only when time.sleep() is called keeps the loop's
    iteration count identical to production while making the test
    instant."""
    state = {"now": 1_700_000_000.0}
    monkeypatch.setattr("src.driver.time.time", lambda: state["now"])
    monkeypatch.setattr("src.driver.time.sleep", lambda s: state.__setitem__("now", state["now"] + s))
    return state


def test_default_notify_action_sends_slack_when_incomplete(monkeypatch):
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("notify")

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == []
    assert len(sent) == 1
    assert "31%" in sent[0]


def test_notify_action_stays_quiet_when_already_100(monkeypatch):
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("notify")

    drv._handle_study_completion_action({"upload_percent": "100"})

    assert sent == []


def test_skip_action_taps_skip_and_logs_no_confirm_dialog(monkeypatch):
    """Some states (e.g. upload already complete) may not show the
    follow-up confirmation dialog at all -- a single Skip tap must still
    succeed and log normally."""
    monkeypatch.setattr("src.driver.time.sleep", lambda *_: None)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("skip", skip_confirm_visible=False)

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Skip"]
    assert ("study_completion_action", {"action": "skip"}) in drv.reporter.events
    assert sent == [], "skip must not also send the notify-mode Slack message"


def test_skip_action_confirms_the_are_you_sure_dialog(monkeypatch):
    """Real gap caught live, 2026-08-18: tapping Skip when the study
    upload is incomplete brings up an "Upload is not complete... Are you
    sure you want to skip the upload?" dialog (confirmed via a real
    device screenshot) whose confirm button is "Yes, Skip" -- not a
    second tap of plain "Skip". The dialog also has a plain X close
    button that cancels, so this must land on the exact confirm text,
    never fall through to that instead."""
    monkeypatch.setattr("src.driver.time.sleep", lambda *_: None)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("skip", skip_confirm_visible=True)

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Skip", "Yes, Skip"]
    assert ("study_completion_action", {"action": "skip"}) in drv.reporter.events


def test_upload_action_taps_upload_and_verifies_progress(monkeypatch):
    _use_fake_clock(monkeypatch)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload", upload_percent_after="100")

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Upload"]
    logged = dict(drv.reporter.events)["study_completion_action"]
    assert logged == {"action": "upload", "upload_percent_before": "31",
                       "upload_percent_after": "100", "success_screen_detected": False}
    assert sent == [], "must not fall back to notify once the tap visibly worked"


def test_upload_action_detects_success_screen_and_taps_ok(monkeypatch):
    """Real gap caught live, 2026-08-18: a fully successful upload
    replaces the whole screen with a "Your study has been completed.
    Please return the device to the provider." success state that no
    longer shows the "Data Upload: N%" label at all -- waiting for that
    label's number to change would have hung the full timeout and then
    falsely reported failure on a perfectly successful upload."""
    _use_fake_clock(monkeypatch)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload", success_screen=True)

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Upload", "Ok"]
    logged = dict(drv.reporter.events)["study_completion_action"]
    assert logged == {"action": "upload", "upload_percent_before": "31",
                       "upload_percent_after": None, "success_screen_detected": True}
    assert sent == [], "must not fall back to notify when the success screen is detected"


def test_upload_action_falls_back_to_notify_when_percent_unchanged(monkeypatch):
    """Negative control for the happy path above: if the tap didn't
    actually move the percentage (and the success screen never appears
    either), this must not silently succeed -- falls back to the same
    human heads-up 'notify' mode always sends, after actually waiting
    out the full poll budget rather than giving up instantly."""
    clock = _use_fake_clock(monkeypatch)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload", upload_percent_after="31")  # unchanged

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Upload"]
    assert len(sent) == 1
    assert "didn't change" in sent[0]
    assert clock["now"] >= 1_700_000_000.0 + 300, "must actually wait out the full poll budget, not bail early"


def test_upload_action_falls_back_to_notify_when_tap_raises(monkeypatch):
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload", tap_raises=True)

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert ("study_completion_action_failed", {"action": "upload", "error": "tap failed"}) in drv.reporter.events
    assert len(sent) == 1
    assert "failed" in sent[0]


def test_upload_action_skips_tap_when_already_100(monkeypatch):
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload")

    drv._handle_study_completion_action({"upload_percent": "100"})

    assert drv._tap_calls == []
    assert sent == []


def test_unrecognized_action_falls_back_to_notify_behavior(monkeypatch):
    """Defensive: an unexpected/future config value must not silently do
    nothing and must not crash -- behaves like the safe "notify" default."""
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("some_future_value")

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == []
    assert len(sent) == 1


# ── upload_percent=None (parse failure) -- code review finding, 2026-08-18 ──
# _detect_study_completed() already confirmed "Study Overview" + an
# Upload/Skip button really is on screen before this is ever called, so a
# None here means only the % regex failed to match -- must be treated as
# "known incomplete", never as silent "nothing to do".

def test_notify_action_still_fires_when_upload_percent_unparseable(monkeypatch):
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("notify")

    drv._handle_study_completion_action({"upload_percent": None})

    assert len(sent) == 1
    assert "unknown" in sent[0]


def test_upload_action_still_taps_when_upload_percent_unparseable(monkeypatch):
    """The Upload button is confirmed present on screen regardless of
    whether the % could be read, so attempting the tap is still safe --
    must not skip it just because the percent is unknown."""
    clock = _use_fake_clock(monkeypatch)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload")  # upload_percent_after=None -> re-scrape also fails

    drv._handle_study_completion_action({"upload_percent": None})

    assert drv._tap_calls == ["Upload"]
    logged = dict(drv.reporter.events)["study_completion_action"]
    assert logged == {"action": "upload", "upload_percent_before": None,
                       "upload_percent_after": None, "success_screen_detected": False}
    # Can't confirm success either way when the percent can't be read --
    # falls back to notify rather than assuming it worked, only after
    # actually waiting out the full poll budget.
    assert len(sent) == 1
    assert "couldn't be read" in sent[0]
    assert clock["now"] >= 1_700_000_000.0 + 300


def test_upload_action_with_unparseable_percent_that_resolves_after_tap(monkeypatch):
    """Negative-control-adjacent: if the re-scrape after tapping DOES
    successfully read a percent (even though the before-value didn't
    parse), that's still meaningfully different from "before" and must
    count as progress, not trigger the didn't-change fallback."""
    _use_fake_clock(monkeypatch)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload", upload_percent_after="100")

    drv._handle_study_completion_action({"upload_percent": None})

    assert drv._tap_calls == ["Upload"]
    logged = dict(drv.reporter.events)["study_completion_action"]
    assert logged == {"action": "upload", "upload_percent_before": None,
                       "upload_percent_after": "100", "success_screen_detected": False}
    assert sent == []
