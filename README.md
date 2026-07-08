# S-Patch AccurKardia Automation

Long-run QA automation for the **S-Patch AccurKardia** app on **Android and iOS**.

It drives the app end-to-end — regression suites, BLE connection and study start,
hourly symptom injection, Bluetooth-loss and airplane-mode fault injection — for
hours or days at a time, with automatic recovery, a web control panel, and Slack
notifications.

> **Platforms** — Android: production-ready · iOS: **Beta** (validated on
> iPhone 13 mini / iOS 18.6.2; requires a Mac host and a signed WebDriverAgent —
> see [iOS Support](#ios-support-beta)).

---

## Highlights

- **Full regression** before each long run — 36+ UI test cases across
  serial-input, settings menu, main screen, symptom diary, and in-study menu
  suites, on both platforms
- **Long-run fault injection** — hourly Log Symptoms entries, periodic
  Bluetooth disconnect (10 min) and airplane-mode (5 min) cycles
- **Self-healing** — unexpected app/system popup dismissal (with screenshot
  evidence), Appium session recovery ladder, app-restart fallback, timezone-DB
  fallback (runs survive hosts without tz data instead of crashing)
- **Web control panel** (port 5003) — platform selector (Android/iOS), device
  list, duration/interval/symptom settings, live suite cards and event log,
  failure artifact browser, one-click distribution ZIP downloads
- **Slack notifications** — run start / each injection / completion / failure
- **Quiet hours** — no injections during configured overnight hours
- **Tester distribution** — self-contained Mac/Windows Standalone ZIPs
  (embedded Node + ADB; Python venv created on first run), published via
  [GitHub Releases](../../releases)

---

## Quick Start

### Testers (recommended)

Download the latest ZIP from [Releases](../../releases):

| Your machine | ZIP | Can test |
|---|---|---|
| Windows | `AccurKardia-Windows-Standalone-*.zip` | Android |
| macOS | `AccurKardia-Mac-Standalone-*.zip` | Android + iOS (Beta) |

Unzip, then double-click **`run.command`** (Mac) or **`run.bat`** (Windows).
Everything installs itself on first run; a browser opens at
`http://localhost:5003`. Pick the platform and device, enter the S-Patch
serial, and press **Start Test**.

> A study must be **registered in the AccurKardia web system** before starting.

### Developers

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Web control panel
make web                                             # → http://localhost:5003

# Or run headless from the CLI
python src/main.py     --config config/accurkardia.yaml       # Android
python src/main_ios.py --config config/accurkardia_ios.yaml   # iOS (Mac only)

# Useful flags: --dry-run (validate config), --once (single injection),
#               --skip-regression
```

---

## What a Run Does

```
regression (serial → menu → main → diary → menu-study [→ connectivity])
        │
        ▼
go_to_main  — enter serial, connect S-Patch over BLE, start the study
        │
        ▼
long run    — every hour: inject a symptom via Log Symptoms
              every hour: BT off 10 min → back on → airplane 5 min → off
              (injection waits while a fault cycle is active)
```

Every step emits structured events (`output/<run>/events.jsonl`) that power the
web dashboard, the HTML report, and Slack messages. Failures save screenshots
and page sources under the run's `screenshots/` and `logs/` folders.

---

## Regression Suites

| Suite | Prerequisite | TCs | Covers |
|---|---|---|---|
| `serial` | app at Step 1 | 8 | serial input, Connect enablement, 950 popup |
| `menu` | app at Step 1 | 9 | settings menu, version/patch-placement screens |
| `main` | study active | 7 | status cards, tabs, live ECG |
| `diary` | study active | 6 | Log Symptoms sheet, save/close flows |
| `menu-study` | study active | 6 | device/study info during a study |
| `connectivity` | Android only | 8 | BT/WiFi status card reactions |

When a study is already active, Step 1 suites are skipped automatically and the
run proceeds to the in-study suites.

---

## iOS Support (Beta)

Feature parity with Android (same suites, injection, BT/airplane cycles), with
platform-specific engineering under the hood:

- **React Native flat accessibility tree** — several screens expose no
  individual elements on iOS, so the driver uses keyboard key-tap typing,
  page-source state readback, runtime-calibrated pixel scans (button/stepper
  detection), and ratio-based coordinate taps. A request to add `testID`s to
  the app (which removes these workarounds) is tracked in
  [`docs/testid_request_ios.txt`](docs/testid_request_ios.txt).
- **Bluetooth fault injection** uses the Settings app switch — the Control
  Center tile only disconnects accessories and leaves app BLE links alive.
- **WebDriverAgent** starts automatically via `pymobiledevice3` (no Xcode at
  runtime). For tester machines, a pre-signed `WDA.ipa` (built once by the
  admin with `scripts/build_wda_ipa.sh`, team-signed, registered-UDID devices
  only) is bundled into the Mac ZIP and installed automatically.
- **System alert resilience** — nightly iOS OTA-update alerts are dismissed
  automatically (`autoDismissAlerts` + recovery-cycle alert handling).

Current limitations: validated on a single device (iPhone 13 mini, iOS 18.6.2);
new tester devices need their UDID registered to the Apple Developer team
before WDA can be installed.

---

## Configuration

`config/accurkardia.yaml` (Android) / `config/accurkardia_ios.yaml` (iOS):

```yaml
run:
  duration_hours: 72                 # total run length
  symptom_interval_hours: 1          # injection cadence
  quiet_hours: {start: 2, end: 6}    # no injections overnight
  bt_disconnect_interval_hours: 1    # 0 disables the BT cycle
  bt_disconnect_minutes: 10
  airplane_mode_interval_hours: 1    # 0 disables the airplane cycle
  airplane_mode_minutes: 5

android:                             # or `ios:` in the iOS config
  udid: "..."                        # adb devices / idevice_id -l
  test_serial_number: "510131"       # S-Patch serial

slack:
  enabled: true
  webhook_url: ""                    # or SLACK_WEBHOOK_URL in .env
```

---

## Building Distribution ZIPs

```bash
# Standalone bundles (embedded Node + ADB) — what testers download
python scripts/build_dist_bundle_mac.py --out ~/Desktop
python scripts/build_dist_bundle.py     --out ~/Desktop   # Windows

# iOS: build the pre-signed WebDriverAgent once (admin Mac, Xcode required);
# the resulting runtime/WDA.ipa is picked up by the next Mac bundle build
bash scripts/build_wda_ipa.sh

# Lightweight source ZIPs (system Python/Node required on the tester machine)
python scripts/build_dist.py            # Mac + Windows → ~/Desktop
```

---

## Project Structure

```
AK-automation/
├── config/                       # per-platform run configs
├── src/
│   ├── main.py / main_ios.py     # long-run entry points
│   ├── scheduler.py              # APScheduler wrapper (+ UTC fallback)
│   ├── driver.py / driver_ios.py # AndroidDriver / IOSDriver
│   ├── workflows/
│   │   ├── symptom_inject(_ios).py     # Log Symptoms injection
│   │   ├── bt_disconnect.py            # Android BT cycle (ADB)
│   │   ├── airplane_mode.py            # Android airplane cycle (ADB)
│   │   ├── connectivity_ios.py         # iOS BT/airplane (Settings / CC)
│   │   └── popup_handler.py            # known + generic error popups
│   └── regression/               # suites: *_ios.py mirrors for iOS
├── web/                          # Flask control panel (port 5003)
├── scripts/                      # dist builders, WDA build, env setup
├── docs/
│   ├── bug_reports/              # filed app bugs w/ evidence
│   └── testid_request_ios.txt    # RN testID request for the app team
├── output/                       # per-run events, screenshots, logs
└── CHANGELOG.md
```

---

## App Under Test

| | Android | iOS |
|---|---|---|
| Bundle / package | `com.wellysis.accurkardia.accurkardia.mobile` | `com.wellysis.accurkardia.accurkardia` |
| Appium driver | UiAutomator2 | XCUITest |
| UI framework | React Native (text-based selectors) | React Native (flat tree — see iOS notes) |

---

## Troubleshooting

- **"Test failed — No time zone found with key …" (Windows)** — fixed in
  v1.0.6 (`tzdata` bundled + UTC fallback). Reinstall from the latest ZIP.
- **Run stalls on an unexpected popup** — generic error popups and iOS system
  alerts are auto-dismissed since v1.0.6; evidence screenshots are saved to the
  run's artifacts.
- **iOS: WDA won't install on a tester iPhone** — the device UDID must be
  registered to the Apple Developer team; the installer prints the UDID to send
  to the admin.

See [`CHANGELOG.md`](CHANGELOG.md) for the full release history.
