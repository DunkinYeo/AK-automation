# S-Patch AccurKardia Automation

Long-run test automation tool for the S-Patch AccurKardia app.
Periodically injects symptoms (Log Symptoms) during ECG monitoring sessions
and sends Slack notifications on start, injection results, completion, and failure.

---

## Features

- **Long-run automation**: Symptom injection at configurable intervals over the test duration
- **Auto-recovery**: Popup detection, app restart, Appium session recovery
- **Slack notifications**: Run start / injection result / complete / failed
- **Quiet Hours**: Skip injections during configured overnight hours
- **Regression tests**: 7 suites, automated UI TC verification
- **Web UI**: Browser-based control, monitoring, and log viewer (port 5002)
- **Distribution ZIP**: Auto-build Mac / Windows deployment packages

---

## Requirements

| Item | Version |
|------|---------|
| Python | 3.10+ |
| Node.js | 18+ |
| Appium | 2.x |
| ADB (android-platform-tools) | latest |
| Android device | USB Debugging enabled |

The AccurKardia app must be in an **active study state** ("My Study Progress" screen visible).

---

## Quick Start (macOS)

```bash
# 1. First time — install environment
./install.command        # or: bash scripts/setup_env.sh

# 2. Run
./run.command            # Appium + web server + browser auto-open

# 3. Stop
./STOP.command
```

## Quick Start (Windows)

```
install.bat   ← first time only
run.bat       ← run
STOP.bat      ← stop
```

---

## CLI

```bash
# Activate virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Long-run test
python src/main.py --config config/accurkardia.yaml

# Validate config only (no device connection)
python src/main.py --config config/accurkardia.yaml --dry-run

# Single injection then exit
python src/main.py --config config/accurkardia.yaml --once
```

---

## Web UI

```bash
make web
# → http://localhost:5002
```

- Device selection / S-Patch serial input / duration and interval settings
- Regression test execution and result display
- Failure artifact browser (`/failures`)
- **⬇ Mac** / **⬇ Windows** buttons in the header to download distribution ZIPs

---

## Makefile

```bash
make install          # create venv + install packages
make run              # long-run test
make web              # web UI (port 5002)
make dry-run          # validate config only

# Regression
make regression       # run all suites
make reg-main         # Main Screen TCs
make reg-diary        # Log Symptoms TCs
make reg-menu-study   # Study menu TCs
make reg-serial       # Serial input TCs
make reg-menu         # Settings menu TCs
make reg-signal       # Check Incoming Signal TCs
make reg-study        # Review Study Setting TCs

# Distribution ZIPs
make dist             # Mac + Windows → ~/Desktop
make dist-mac
make dist-windows
make dist OUT=/tmp    # custom output path
```

---

## Configuration

Key fields in `config/accurkardia.yaml`:

```yaml
run:
  duration_hours: 72               # total test duration (h)
  symptom_interval_hours: 1        # injection interval (h)
  quiet_hours: {start: 2, end: 6}  # skip injections during these hours

android:
  udid: "55ETQWBXYE1RA1"           # check with: adb devices
  test_serial_number: "610260"     # S-Patch serial number

slack:
  enabled: true
  webhook_url: ""                  # set via .env SLACK_WEBHOOK_URL or directly
  mention: ""                      # Slack User ID (e.g. U0123ABC)
```

Slack webhook via `.env` file:

```bash
echo "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..." > .env
```

---

## Regression Test Suites

| Suite | Prerequisite | TCs | Description |
|-------|-------------|-----|-------------|
| `serial` | Device connected | 6 | Serial number input screen |
| `menu` | Device connected | — | Step 1 settings menu |
| `signal` | BLE connected, no study | — | Check Incoming Signal |
| `study` | BLE connected, no study | — | Review Study Setting |
| `main` | **Study active** | 6 | Measurement main screen |
| `diary` | **Study active** | 6 | Log Symptoms sheet |
| `menu-study` | **Study active** | 6 | Side menu during study |

Web UI default suites: `main, diary, menu-study` (study-active state)

---

## Project Structure

```
AK-automation/
├── install.command / run.command / STOP.command   # macOS launchers
├── install.bat / run.bat / STOP.bat               # Windows launchers
├── Makefile
├── requirements.txt
├── config/
│   ├── accurkardia.yaml       # main config
│   └── run.example.yaml       # template for adding new apps
├── src/
│   ├── main.py                # long-run entry point
│   ├── run_regression.py      # regression entry point
│   ├── scheduler.py           # injection scheduler
│   ├── driver.py              # AndroidDriver (text-based selectors)
│   ├── slack.py               # Slack notifications
│   ├── workflows/
│   │   ├── measurement_start.py   # navigate to main screen
│   │   └── symptom_inject.py      # symptom injection flow
│   └── regression/
│       ├── runner.py          # TC executor
│       ├── main_screen.py     # Main Screen TCs
│       ├── add_diary.py       # Log Symptoms TCs
│       ├── menu_study.py      # Menu Study TCs
│       ├── serial_input.py    # Serial TCs
│       └── helpers.py         # reset_to_step1, go_to_main
├── web/
│   ├── app.py                 # Flask server (port 5002)
│   └── templates/
│       ├── index.html         # main UI
│       ├── failures.html      # failure artifact list
│       └── failure_detail.html
├── scripts/
│   ├── build_dist.py          # distribution ZIP builder
│   └── setup_env.sh           # macOS environment setup
├── artifacts/                 # failure screenshots / logs
└── output/                    # run results (JSONL event log)
```

---

## Building Distribution ZIPs

```bash
python scripts/build_dist.py                    # Mac + Windows → ~/Desktop
python scripts/build_dist.py --out /tmp         # custom path
python scripts/build_dist.py --platform mac     # Mac only

# via Makefile
make dist
```

Output:
- `AccurKardia-Mac-YYYYMMDD.zip`
- `AccurKardia-Windows-YYYYMMDD.zip`

ZIP structure: launchers at root, source code under `automation/`

---

## App Info

| Field | Value |
|-------|-------|
| Package | `com.wellysis.accurkardia.accurkardia.mobile` |
| Activity | `com.wellysis.accurkardia.accurkardia.mobile.MainActivity` |
| Language | English (follows device language setting) |
| UI | React Native — no resource-id, text-based selectors |
| Appium Driver | UiAutomator2 |
