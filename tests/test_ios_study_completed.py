"""
Regression tests for issue #18: IOSDriver._detect_study_completed(), the
iOS mirror of AndroidDriver._detect_study_completed() (#11) that's needed
for until_study_end mode to actually work on iOS instead of silently
running to the safety-cap duration.

The fixture (tests/fixtures/ios_study_overview_source.xml) is the REAL
XCUITest page_source captured live from a physical iPhone 13 mini
(iOS 18.6.2) that had genuinely reached this screen after ~24h, via
output/ios_20260731_120249 (2026-07-31) — not a hand-written guess at the
structure. Matching is by text content and tree adjacency (label="X"
followed by a separate label="value" node), not screen coordinates, so it
should hold across other iPhone screen sizes in principle — but this has
only been verified against this one physical device; there was no second
iPhone available to confirm across devices the way the Android version
was (Pixel 7 + a Samsung device, per README's iOS Support section).

Run: .venv/bin/pytest tests/test_ios_study_completed.py -v
"""
from pathlib import Path
from unittest import mock

from src.driver_ios import IOSDriver

FIXTURE = (Path(__file__).parent / "fixtures" / "ios_study_overview_source.xml").read_text()


def _make_driver(page_source: str, *, visible_texts: set[str]):
    drv = IOSDriver.__new__(IOSDriver)
    drv.reporter = mock.Mock()
    drv.artifacts = mock.Mock()
    drv.drv = mock.Mock()
    drv.drv.page_source = page_source
    drv.is_visible_text = lambda text, contains=True, timeout=2: text in visible_texts
    drv.screenshot = mock.Mock(return_value="")
    return drv


def test_detects_real_study_overview_screen():
    drv = _make_driver(FIXTURE, visible_texts={"Study Overview", "completed"})
    assert drv._detect_study_completed() is True
    assert drv._study_completed is True


def test_extracts_percentages_and_times_from_real_fixture():
    drv = _make_driver(FIXTURE, visible_texts={"Study Overview", "completed"})
    drv._detect_study_completed()
    event_name, data = drv.reporter.log_event.call_args[0]
    assert event_name == "study_completed_ios"
    assert data["study_percent"] == "100"
    assert data["upload_percent"] == "100"
    assert data["study_start"] == "2026-07-30 14:04:20"
    assert data["study_end"] == "2026-07-31 14:04:20"


def test_negative_control_no_study_overview_text_returns_false():
    """If 'Study Overview' isn't actually visible (a normal in-study
    screen), this must not false-positive just because the page_source
    happens to be passed in — is_visible_text is the real gate."""
    drv = _make_driver(FIXTURE, visible_texts=set())  # nothing "visible"
    assert drv._detect_study_completed() is False
    assert not getattr(drv, "_study_completed", False)
    drv.reporter.log_event.assert_not_called()


def test_cached_true_short_circuits_without_rechecking():
    drv = _make_driver(FIXTURE, visible_texts={"Study Overview", "completed"})
    drv._study_completed = True
    assert drv._detect_study_completed() is True
    drv.is_visible_text = mock.Mock(side_effect=AssertionError("should not be called"))
    assert drv._detect_study_completed() is True
