# Team share report (ko / en PDF)

Builds the team results document (summary → regression → long run → reconnection
ledger → app issues) in Korean and English, as HTML and PDF.

```bash
python -m share_report.build share_report/data/example_ak.json          # ko + en → output/share/
python -m share_report.build <report>.json --lang en --results <results>        # one language, other results
```

- **Report file** (`data/<date>_<app>.json`): every fixed text is `{"ko": "...", "en": "..."}`.
  Section types: `table`, `key` (one key finding with a timeline), `ledger`
  (reconnection scenarios), `list`. `**text**` is bold. Tile `{"n": "auto:ledger"}`
  counts ledger results.
- **Scenarios**: `reconnect_scenarios.json` (49, bilingual how/check).
- **Results**: JSON keyed by scenario id, an ArtifactData dump directory, or the
  results page CSV export. Each result has `note` (Korean) and `note_en`
  (English). Testers write both; the results page has an English memo box.
- **English check**: the English build stops if any Hangul is left and names the
  field (most often a result with a Korean memo but no English memo).
- **PDF**: headless Chrome or Edge (`CHROME_PATH` to override). Without one, the
  HTML is still written; open it and print to PDF.

## Filled in from the runs

`auto_recent.json` needs no typing: `{"type": "auto_regression"}` and
`{"type": "auto_longrun"}` sections and `auto:regression` / `auto:symptoms`
tiles are built from `output/<run>/events.jsonl` (suite results, symptom
entries, airplane/BT checks, app log export, how the run ended).
`"since_days": 7`, or `--since/--until YYYY-MM-DD`, picks the runs. Dashboard
regression runs (`run_regression.py`) write the same `regression_suite_result`
event to `output/regression/events.jsonl`.

**Dashboard**: Progress card → **📄 Share PDF** → pick a report file → *Make ko +
en PDF*. Files go to `output/share/` and are linked for download.
