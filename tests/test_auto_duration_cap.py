"""
Regression test: Auto (until study end) mode must not cap a run at 168h.

Caught live 2026-11-12 (output/20261105_160917): a ~26-day AK study was at
27% when the 168h cap hit, so the run ended with run_complete and the
dashboard showed "Test complete" while the app study was still going.

Run: .venv/bin/pytest tests/test_auto_duration_cap.py -v
"""
import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "web" / "templates" / "index.html"


def test_auto_mode_cap_covers_a_26_day_study_with_margin():
    html = TEMPLATE.read_text()
    m = re.search(r"const AUTO_MAX_HOURS = (\d+);", html)
    assert m and int(m.group(1)) >= 1080
    assert "=== 'auto'\n                       ? AUTO_MAX_HOURS" in html
