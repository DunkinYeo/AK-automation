"""
Regression tests for device-timezone handling in _parse_app_log_line()
(src/log_timeline.py).

Raised 2026-08-12: a device set to a US timezone would previously merge
app-log rows into wildly wrong positions on the timeline, because the
old parser read the log line's GMT offset but discarded it -- the H:M:S
digits were treated as if they were already this host's local time. The
same class of bug already hit driver.py's Study Overview scraping once
for real (2026-07-21, device_tz_offset_seconds): a tester's phone set to
America/Chicago made study_end look ~14h off from the report's own
timestamps.

These tests are deliberately host-timezone-independent (don't assert an
absolute wall-clock value, since CI runners and this dev machine sit in
different timezones) -- instead they check that two lines describing the
same real-world instant under different device offsets parse to the
*same* converted value, which only holds if the offset is actually being
applied.

Run: .venv/bin/pytest tests/test_log_timeline_device_timezone.py -v
"""
from src.log_timeline import _parse_app_log_line

_TAIL = " [S-Patch AccurKardia] - [Category] [Sub] Message"


def test_same_instant_different_device_offsets_converge():
    """GMT-0500 00:18:48 and GMT+0900 14:18:48 on the same date are the
    same real-world instant (UTC 05:18:48 both ways) -- must parse to the
    identical host-local datetime regardless of what timezone this host
    itself is in."""
    line_chicago = "[Tue Aug 11 2026 00:18:48 GMT-0500]" + _TAIL
    line_seoul = "[Tue Aug 11 2026 14:18:48 GMT+0900]" + _TAIL

    dt_chicago, rest_chicago = _parse_app_log_line(line_chicago)
    dt_seoul, rest_seoul = _parse_app_log_line(line_seoul)

    assert dt_chicago == dt_seoul
    assert rest_chicago == rest_seoul == "[Category] [Sub] Message"


def test_different_instant_same_wallclock_diverges():
    """Negative control: two lines with the *same* printed wall-clock time
    but different device offsets describe different real-world instants,
    so they must NOT converge -- confirms the test above isn't trivially
    passing because parsing ignores the offset entirely (the pre-fix bug)."""
    line_chicago = "[Tue Aug 11 2026 00:18:48 GMT-0500]" + _TAIL
    line_seoul = "[Tue Aug 11 2026 00:18:48 GMT+0900]" + _TAIL

    dt_chicago, _ = _parse_app_log_line(line_chicago)
    dt_seoul, _ = _parse_app_log_line(line_seoul)

    assert dt_chicago != dt_seoul


def test_malformed_offset_rejected_not_crashed():
    line = "[Tue Aug 11 2026 00:18:48 GMTZZ00]" + _TAIL
    assert _parse_app_log_line(line) is None
