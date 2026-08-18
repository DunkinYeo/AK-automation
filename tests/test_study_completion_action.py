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


def _make_driver(action, upload_percent_after=None, tap_raises=False):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.reporter = _FakeReporter()
    drv._study_complete_action = action
    drv._slack_webhook = "https://hooks.slack.com/services/fake"
    drv._tap_calls = []
    src = f'text="Data Upload" text="{upload_percent_after}"' if upload_percent_after is not None else ""
    drv.drv = _FakeInnerDriver(page_source=src)

    def _tap_text(text, timeout=5, contains=True):
        drv._tap_calls.append(text)
        if tap_raises:
            raise RuntimeError("tap failed")

    drv.tap_text = _tap_text
    return drv


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


def test_skip_action_taps_skip_and_logs(monkeypatch):
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("skip")

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Skip"]
    assert ("study_completion_action", {"action": "skip"}) in drv.reporter.events
    assert sent == [], "skip must not also send the notify-mode Slack message"


def test_upload_action_taps_upload_and_verifies_progress(monkeypatch):
    monkeypatch.setattr("src.driver.time.sleep", lambda *_: None)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload", upload_percent_after="100")

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Upload"]
    logged = dict(drv.reporter.events)["study_completion_action"]
    assert logged == {"action": "upload", "upload_percent_before": "31", "upload_percent_after": "100"}
    assert sent == [], "must not fall back to notify once the tap visibly worked"


def test_upload_action_falls_back_to_notify_when_percent_unchanged(monkeypatch):
    """Negative control for the happy path above: if the tap didn't
    actually move the percentage, this must not silently succeed --
    falls back to the same human heads-up 'notify' mode always sends."""
    monkeypatch.setattr("src.driver.time.sleep", lambda *_: None)
    sent = []
    monkeypatch.setattr("src.slack.slack_notify", lambda webhook, msg: sent.append(msg))
    drv = _make_driver("upload", upload_percent_after="31")  # unchanged

    drv._handle_study_completion_action({"upload_percent": "31"})

    assert drv._tap_calls == ["Upload"]
    assert len(sent) == 1
    assert "didn't change" in sent[0]


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
