# Changelog — S-Patch AccurKardia Automation

## [v1.1.4] — Unreleased

### Highlights
Three new capabilities (#55, #69, and the "On Study Completion" setting
below) plus a batch of real bugs found by watching actual multi-day runs
on the dashboard — several only surfaced because a tester was staring
at a live run and noticed something looked wrong, not from code review.

### App log capture & Log Timeline View (#55, #69)
- **The app's own internal log can now be pulled from the device and
  compared side-by-side with automation events on a single timeline.**
  A "Capture App Logs" button (web UI, works mid-run without disrupting
  the active session) drives AccurKardia's hidden log-export screen and
  pulls the resulting zip; it's also captured automatically at the end
  of every run (success or failure) so a Log Timeline is available even
  when nobody thought to click the button — the case that matters most
  (a crash) is exactly the one a manual click can't reach after the
  fact.
- The saved report (`summary.html`) and the live web report both show a
  merged, time-ordered view — app-log lines and automation events
  side by side with source badges — plus a live-updating `/log-timeline`
  page and a keyword-highlighted "Log Highlights" summary
  (error/fail/exception/bluetooth/disconnect/upload/study/timeout).
- **Real bugs found while building and using this against actual live
  runs:**
  - App log timestamps carry the *device's* own GMT offset, not
    necessarily the host machine's — a device set to a different
    timezone than the automation host would have merged rows into
    wildly wrong positions on the timeline. Each line is now converted
    from its own embedded offset instead of assuming it already matches
    host-local time (same class of bug #11's Study Overview
    start/end-time scraping hit for real once already).
  - The same study/session re-exports to the *same* filename every
    capture — a stale copy from an earlier capture already sitting on
    the device could pass the "is the download done yet" stability
    check before the new export had even started writing, silently
    pulling stale data. The old file is now deleted right before each
    new capture.
  - A capture at run end could leave the app stranded on whatever
    screen the export flow finished on, with nothing to notice or
    recover it — now always attempts to return to a known-reachable
    screen afterward, success or failure.
  - **A normal, successful study completion used to break the run-end
    capture entirely**: the app is sitting on the Study Overview
    (Upload/Skip) screen at that point, which the tester may still need
    — the capture flow's own screen-recovery logic would press Back
    trying to escape it to reach Setting/Version Information, disturbing
    the exact screen that mattered most. Run-end capture is now skipped
    in this one case (earlier hourly captures during the run already
    cover most of what one more at the very end would add).
  - A tester watching a live run mid-capture-gap could misread a stale
    (not-recently-recaptured) app log as "the app stopped logging" —
    the timeline now marks exactly where the app log's own coverage
    ends and shows how long ago it was last captured, with a one-click
    re-capture from the timeline page itself.
  - A manual capture *after* a run had already ended used to vanish
    into an unrelated standalone folder instead of that run's own
    report — now routed into the run's own directory (falling back to
    the most recently active run if the web server itself was restarted
    since), and the saved report is re-rendered on the spot so it picks
    up the new capture instead of staying frozen at whatever it looked
    like when the run originally finished.
  - The report now also records a capture history — when the app log
    was captured during a run, how many times, and whether each attempt
    succeeded, failed, or was skipped.

### "On Study Completion" run setting — notify / auto-upload / auto-skip
- The Study Overview screen (#11) always has both Upload and Skip
  buttons, and automation only ever sent a Slack heads-up asking a human
  to tap one manually. Real evidence this session: `upload_percent` sat
  at 31% and 99% on two separate completed runs — genuinely worth
  automating, but auto-tapping Upload unconditionally isn't right
  either, since not every run's study data needs to actually be
  uploaded (e.g. a synthetic QA test run). Made it a per-run tester
  choice in the web UI's run-setup form instead of a fixed behavior.
- New "On Study Completion" dropdown, default **Notify only** (preserves
  the exact original behavior — nothing changes unless a tester opts
  in): **Auto-tap Upload** taps Upload, then polls up to 300s (upload
  duration is unpredictable — could be a large dataset) for either the
  Data Upload % to move or the completion screen to appear, falling back
  to the same Slack notification only if neither happened, so this never
  fails more silently than doing nothing would have. **Auto-tap Skip**
  taps Skip.
- **Three real gaps found before/during this feature's first live test,
  fixed before it ever ran fully unattended**: an unparseable Data
  Upload % (`up is None`) used to silently do nothing at all in every
  mode, not just skip the upload-specific logic — now treated the same
  as "known incomplete" (code review finding). Tapping Skip when upload
  is incomplete also brings up a second "Are you sure you want to skip
  the upload?" dialog (confirmed via a real device screenshot) whose
  confirm button is "Yes, Skip", not a repeat of "Skip" — now handled.
  And a fully successful upload replaces the whole screen with a
  completion message and an "Ok" button — the "Data Upload: N%" text
  disappears entirely, which the original percent-only check would have
  misread as "didn't change" and falsely escalated to Slack; now detects
  the completion screen directly and taps "Ok".
- Android only (matches `_detect_study_completed()`'s existing scope —
  iOS has its own separate study-completion implementation, untouched).

### A run whose study was never actually started no longer wastes days
- **Real incident**: a run was started with the app study never
  registered/started on the device (still on "Connect Your S-Patch").
  Regression suites correctly reported "Study not started" as ordinary
  TC failures in 3 separate suites, but nothing stopped the scheduler
  from starting anyway — it went on to schedule 40+ hourly jobs that all
  failed identically ("Session recovery failed") over roughly 43 hours
  before anyone noticed. A final precondition check right before the
  scheduler starts now catches this and aborts immediately with a clear
  error instead — reusing the same main-screen check every job already
  relies on, so it adds no new failure mode, just moves an existing one
  much earlier.

### Faster study-completion detection
- The automation previously only checked whether the app study had
  finished once per scheduled injection job (hourly by default) — fine
  for most of a multi-day run, but a run whose last job happened to fail
  a connectivity hiccup could take up to an hour longer than necessary
  to notice the study was actually done, and the dashboard's "App
  Study: N%" reading could sit stale for the same reason. Once the last
  known reading crosses 95%, the connectivity monitor now also checks
  every 30 seconds — no added overhead for the rest of a run's duration,
  since it only activates in the final stretch.
- The "App Study" progress indicator now shows how long ago its last
  reading was taken, and flags itself once that reading is stale enough
  to plausibly be out of date.

### Dashboard fixes (found via live usage)
- **Battery status reporting was broken for the actual normal case**:
  the device's real "battery is fine" text ("Normal") was never in the
  recognized label list, so a healthy battery never updated the
  dashboard and it could stay stuck showing "Not Connected" indefinitely
  after a Bluetooth reconnect. Separately, "Replace" was removed from
  the recognized labels entirely — the app has no such real status text,
  it only ever came from an always-on-screen "How to Replace the
  Battery" tutorial card being misread as a live reading.
- The "Connection" status chip could stay stuck on "pending" forever
  (it was watching for a popup that never actually appears), and the
  battery chip could show a false green checkmark while genuinely
  disconnected instead of "Not Connected".
- Unauthorized USB devices (phone hasn't accepted the "Allow USB
  debugging" prompt yet) used to disappear from the device list with no
  explanation — now shown with a clear warning instead of just vanishing.
- The mid-run "Interval" override box and the pre-start "Injection
  Interval" dropdown could both show misleading values: the override
  box defaulted to a placeholder that looked like a real "1h" reading
  regardless of the run's actual interval, and the dropdown's chosen
  value (e.g. "Every 4 hours") wasn't remembered across a page reload,
  silently reverting to "Every 1 hour". Both now correctly reflect the
  actual running session / the tester's last choice.

### iOS
- Confirmed (and locked in with regression tests) that
  `study_completed_ios` already reaches the dashboard and saved report
  correctly via the existing Android/iOS event-name normalization — no
  code change needed, just verification.
- Cleaned up a stale code comment in `main_ios.py` describing
  `until_study_end` as unsupported on iOS, left over from before #18
  shipped real iOS study-completion detection.

### Hardening
- **The `/app_logs/<path>` download route was narrowed to `*.zip`
  captures only, no longer the whole of `output/`** (code review
  finding). This server binds to all interfaces (the "Share on local
  network" URL shown at startup), so anyone on the same LAN could
  previously browse/download any run's screenshots, `events.jsonl`, or
  `summary.html` by guessing a path, not just app-log zips. Doesn't
  change what the app's own internal links ever request — they always
  hand back exact real paths already — only narrows what an arbitrary
  guessed path is allowed to reach.
- A run whose output directory couldn't be resolved right after a rapid
  restart (real incident: three run restarts ~70s apart) used to latch
  onto a *different*, still-finishing previous run's directory instead
  of its own, because the matching logic used filesystem mtime (which
  any process's file write can bump) instead of the directory's own
  immutable, run-specific name. The dashboard stayed stuck showing the
  wrong run's data for the rest of the session once this happened.
- The dashboard's re-attached-run identity check (`ps`/`Get-CimInstance`,
  called on every status poll) had only a 5s timeout — on a machine
  under real concurrent load, a single slow `ps` call could trip it,
  and the existing fail-closed safety behavior would then wipe the
  tracked run's state even though the process was still genuinely alive
  and correctly ours (observed 4-5 times in one session). Widened to
  15s; the fail-closed behavior itself is unchanged.
- **The connectivity regression suite (TC-CONN-001..005) failed
  outright on a live run** (#92): it unconditionally tapped a
  "Device Status" nav label to navigate there, but the app's main
  screen already opens directly on Device Status — a fact already
  discovered and fixed elsewhere in `driver.py` back on 2026-07-15, but
  never propagated to this suite. Now only taps the label when it's
  actually a different, active tab offering it as a switch target.

### CI/CD & tooling
- New weekly canary workflow installs Appium/UiAutomator2 at "latest"
  (no version pin) and attempts a real session creation, to catch a
  future repeat of the npm dependency drift that broke a tester's
  first-run install in v1.1.3 before it ever reaches a release.
- `windows-smoke.yml`/`mac-smoke.yml`'s path filters now also cover
  `Makefile` changes, and each other's workflow file — a change scoped
  to just one of these files (or to `Makefile`) previously got stuck
  permanently blocked, since branch protection requires both checks but
  neither's filter covered it (same class of gap the `tests/**`/
  `pytest.ini` filter omission was).
- Widened the Windows Appium-bootstrap smoke test's HTTP timeout
  (30s → 60s) after a real flake: Appium's own retry logic took 28.7s
  to return its expected "no device" response, leaving only ~1.3s of
  margin against ordinary CI runner variance.
- `make restart-web` codifies the SIGKILL-based web server restart
  sequence that lets a web/report code change take effect without
  disrupting an in-progress multi-day run.

### Known issues / deferred
- **USB re-recognition after WiFi ADB use (#62)**: an external Windows
  tester reported the device disappearing from USB after switching to
  WiFi ADB. Not reproduced on this project's own Mac + test device
  combination, and a stronger candidate explanation (an *unauthorized*
  device silently vanishing from the list, now fixed above) hasn't been
  confirmed either — holding off on a speculative code change until an
  actual `adb devices` capture from the failure is available.
- PyInstaller-based standalone packaging (#46) and per-device scoping of
  iOS WDA process cleanup (#26) remain deferred; neither is urgent for
  this release.

## [v1.1.3] — 2026-08-05

### Fixed after initial publish (same tag, assets rebuilt)
- **The standalone Windows/Mac build could fail immediately on first run**
  with a Node.js "Cannot require() ES Module ... in a cycle" error,
  reported by a real external tester. The build scripts installed Appium
  and its UiAutomator2/XCUITest drivers with no version pin, so every
  build silently pulled whatever npm resolved as "latest" — and
  appium-uiautomator2-driver had since jumped 4 major versions, pulling in
  an ESM-only dependency that breaks under Node's `require()`. Pinned to
  the versions actually verified working (appium@3.5.2,
  uiautomator2@4.1.5, xcuitest@11.17.1), confirmed via a real CI build +
  smoke test of the extracted zip.
- **After the pin above, the same tester hit a second first-run failure**:
  `INSTALL_FAILED_VERIFICATION_FAILURE` installing Appium's helper APK
  (`settings_apk-debug.apk`), on the same phone/PC that had worked fine on
  v1.1.2. Root cause: the UiAutomator2 driver pushes/refreshes this helper
  app to the device on every session start (not just the first-ever driver
  install), and Android's Play Protect "Verify apps over USB" blocks its
  debug signature — something that can start happening at any time as npm
  dependency resolution drifts, independent of the tester's environment.
  The app now disables this Android setting automatically before every
  Appium session (`src/driver.py`), so no tester action or re-diagnosis is
  ever needed again; the build scripts also disable it unconditionally on
  every launch as defense in depth for the very first driver install.

### Highlights
This release is overwhelmingly a **reliability pass**, not a feature drop:
of the ~29 tracked issues, only two were new capabilities and the rest were
bug fixes uncovered by reviewing real long-run logs and hardening the
tool's own understanding of "is this run actually still alive." A real
19h+ iOS soak run (and a real 21h+ Android hang) each surfaced a genuine
production bug during this cycle, both fixed and verified against the same
class of failure.

- **A real Appium HTTP hang could freeze a run forever, invisibly.** No
  timeout was configured on the Appium webdriver connection, so a single
  stalled call could block a job indefinitely — and if that happened right
  as an until-study-ends run tried to close out, the whole process could
  hang alive for 21+ hours with `run_complete` never logged, so nothing
  ever alerted. Fixed with a client-side timeout (default 120s); the
  dashboard and reports now also correctly show a finished run as done
  even if a future hang of this kind ever recurs.
- **A silent job-loss bug in the shared Android/iOS scheduler.** If
  escalating session recovery failed during the "session check" or
  "bring to foreground" steps, the failure was never logged — the job
  just vanished from every count and report, with no `job_failed`/
  `job_result` event at all. Found by comparing `job_start` vs `job_result`
  counts in a real run's logs; fixed to log consistently across all three
  health-check steps.
- **iOS WDA/session recovery hardening.** A 19h iOS soak hit "port #8100
  occupied by another process" 41 times because WDA/iproxy processes were
  never tracked or reliably killed between reconnect attempts — including
  2 full recovery failures tied directly to the job-loss bug above. Now
  tracked and killed precisely (both on reconnect and on a normal stop),
  with the port's actual release confirmed before starting a new one.
- **CI/CD is now real CI/CD.** Tag-push release automation, Mac smoke CI,
  and (new) branch protection — `main` requires a PR with the Windows/Mac
  smoke CI (which now runs the new unit test suite) passing before merging.
- **iOS now detects study completion, closing the gap with Android.**
  `until_study_end` mode previously had no way to know an iOS study had
  actually finished, so it just ran to its safety-cap duration. iOS now
  recognizes the real "Study Overview" completion screen the same way
  Android already did, and the web UI's "Auto (until study ends)" toggle
  is enabled for both platforms again.
- **A study-completed iOS run no longer reports fake job failures.**
  Once a study finished, any unrelated hiccup (a slow Appium response, a
  brief WDA blip) during the next hourly check-in caused the recovery
  logic to burn through all 3 recovery steps and log a failed job, even
  though there was nothing left to recover — the run had already ended
  successfully. It now recognizes "study already completed" up front and
  skips cleanly instead.
- A completed-but-hung run's dashboard/report now reads as finished
  instead of stuck "running" — and the saved summary report correctly
  shows PASS for a run that finished via study-completion rather than a
  normal `run_complete`.

### Process identity & "is this run actually still running" (the recurring theme)
A long chain of fixes across this cycle all trace back to the same class
of question — does the tool correctly know whether a tracked process is
really still alive, really still *its own*, and really still doing
anything — surfaced repeatedly as the web server was restarted, PIDs were
reused, and Windows-specific process inspection was hardened:
- `/api/start` now recognizes a re-attached run after a server restart
  and refuses to start a duplicate on top of it.
- A stale `web_run_state.json` (PID reuse after a natural exit) can no
  longer cause a re-attach or Stop to target the wrong process — identity
  is verified against the actual command line, not just liveness.
- A hard-crashed child (SIGKILL, segfault) no longer shows as "running"
  forever in `/api/status`.
- Windows process-identity verification was hardened through several
  rounds: `ps` doesn't exist on Windows (moved to `Get-CimInstance`),
  backslash paths broke the match, a verification failure used to
  fail *open* (dangerous on the one call site that sends a kill signal)
  and now fails closed, and `_run_already_active()`/Inject Now were
  brought in line with the same identity check used elsewhere.
- **`os.kill(pid, 0)` on Windows does not do what the POSIX idiom implies**
  — CPython's Windows implementation calls `TerminateProcess` even for
  signal 0, meaning the existence-check function could have been silently
  killing genuinely-alive Windows processes on every poll. Replaced with
  a real `OpenProcess`/`GetExitCodeProcess` check.
- A loose `"src/main.py" in command_line` substring match could false-
  positive on an unrelated project at the same relative path — now
  compared against this installation's exact resolved path.
- `run_ended_study_complete` (the until-study-ends early-exit signal) is
  now recognized as a terminal state everywhere it's checked (status API,
  team dashboard, saved report) — previously only `run_complete`/
  `run_failed` counted, so a completed-but-not-yet-exited run could show
  as running or, in the saved report, as failed.

### iOS
- **Study-completion detection engine implemented** — mirrors Android's
  text/structure-based screen matching (adapted for iOS's `label=`
  accessibility attributes instead of Android's `text=`), captured and
  verified against a real device's actual completion screen. `run`
  startup also no longer gets stuck in a multi-minute wait loop when a
  run is (re)started against a study that already finished.
- Web Stop now runs cleanup and saves the final report reliably (SIGTERM
  is converted to a clean exit instead of skipping `finally` blocks) —
  verified against a real interrupted run.
- WDA/iproxy processes are tracked and killed precisely on reconnect, on
  a normal stop, and before falling back to Appium's own xcodebuild WDA
  launch — instead of relying only on pattern-matched `pkill` and a fixed
  sleep before the next start.
- Failure artifacts no longer record iOS failures with `platform: android`
  in their metadata.
- The web dashboard's platform/device display now actually reflects the
  running session (it defaulted to Android and never re-synced, even
  while an iOS run was live) — found by a real user looking at the
  dashboard mid-run and noticing the mismatch.

### CI/CD & Testing (new)
- `windows-smoke.yml` / `mac-smoke.yml`: build the real standalone ZIP,
  run the new unit test suite, then smoke-test the bundle with its own
  embedded/venv Python.
- `release.yml`: tag-push (`git tag vX.Y.Z && git push --tags`) now builds
  both standalone ZIPs and publishes a GitHub Release automatically,
  pulling notes from this file — and now fails the release instead of
  publishing empty notes if a tag's CHANGELOG section is missing.
- **Branch protection**: `main` requires a PR with both smoke-CI checks
  passing before merging (repo admin can still push directly for
  emergencies). CI now also runs on the pull request itself, not only
  on push to `main`.
- First permanent unit test suite for this project (`pytest`, see
  `pytest.ini`) — covers process-identity verification, scheduler
  concurrency, the Appium HTTP timeout, terminal-event recognition, job
  recovery logging, and iOS WDA process cleanup.
- Windows standalone builds keep their `requirements.txt` version pins
  again (a reproducibility regression from an earlier release).

### Reporting
- Auto-footnotes a failed regression TC when its "periodic twin" (a
  recurring health check that verifies the same screen/feature) passed
  repeatedly afterward — e.g. a one-time BT-reconnect ECG check failure
  gets a note like *"same-screen check passed 19 times since — likely a
  timing fluke"* instead of just reading as a plain failure.
- `run_complete` notifications now show the actual injection count instead
  of always showing "?".
- `summary.html` was silently failing to generate on every single run
  (a Jinja `tojson()` incompatibility) — now generates correctly, and
  also normalizes iOS's `_ios`-suffixed events so a successful iOS run
  doesn't show as FAIL.
- The web report auto-opens in the browser when an unattended run reaches
  any terminal state (success or failure) — previously you only found out
  by checking the dashboard tab yourself.
- App crash evidence now also captures the OS-level ActivityManager log
  (`Process X has died: reason`), not just Java exception traces — the
  latter alone misses low-memory kills and force-stops, which is most of
  what actually kills the app in the field.

### Known Limitations (carried forward, not new)
- iOS's study-completion detection was verified on a single device
  (iPhone 13 mini) — the matching is text/structure-based, not
  coordinate-based, so it should hold on other screen sizes, but a second
  physical iPhone hasn't been available yet to cross-check the way
  Android's detection was (Pixel 7 + a Samsung device).
- iOS WDA cleanup's `pkill` pattern still isn't scoped to a specific
  device UDID — safe for the current single-device setup, a real risk
  only if multiple iPhones are ever run in parallel.

## [v1.1.2] — 2026-07-21

### Highlights
- The web run's schedule and the app/patch study's own schedule are now tracked separately — the dashboard and report show app study progress alongside run progress, and the tool no longer records fake failures once a study finishes early.
- Android UI navigation (menu open/close, Start Study) now finds elements by their on-screen bounds before falling back to fixed ratio coordinates, so it degrades more gracefully across device models and aspect ratios.
- WiFi ADB Auto Detect now finds and connects every USB-attached device, not just the first one, and verifies each `adb connect` actually succeeded instead of assuming success.
- The web server can now restart (crash, redeploy) without losing track of a run in progress — it re-attaches to the running process instead of leaving a stale "ghost" state.

### App Study Tracking (new)
- Added `study_progress` tracking: after each hourly health check, the tool reads the app's own `My Study Progress N%` and records it — independent of the web run's configured duration, since the two schedules are unrelated.
- The dashboard now shows `App Study: N%` next to run progress, with a linear ETA (`ends ~HH:MM`) once two samples exist, and a warning if the study will finish before the configured run duration.
- Added detection of the post-study "Study Overview" screen (Upload/Skip). Once detected, remaining scheduled jobs are marked `skipped — study ended` instead of failing every hour, and the run's HTML report gets a new **App Study Summary** card: Data Upload %, the app's own recorded study window, and how many injections landed inside vs. after that window.
- If Data Upload is below 100% when the study completes, both the report and Slack now show an explicit **⚠ Action Required: tap 'Upload' in the app** notice.
- Added a **"Until study ends" run mode** (now the default in the web UI): instead of always running for a fixed duration, the run closes out normally as soon as the app study completes — the configured duration still acts as a safety cap (default 168h) if study-completion detection doesn't fire.

### Android Reliability
- Menu/navigation coordinate fallbacks (`Start Study`, `close_menu`) now search for a clickable element within the expected screen region before falling back to a fixed ratio coordinate — verified on both Pixel 7 and a Samsung device with a different aspect ratio.
- Fixed the BT-reconnect ECG check occasionally reporting "View button not found" right after a new study starts — it now retries once, since this was a one-time rendering lag rather than an actual problem (all later hourly checks in the same run had passed).
- Fixed the `study_progress` percent not being read at all in some cases due to too narrow a text-matching window in the app's UI tree.

### Web UI
- Start form: added BT Disconnect / Airplane Mode duration fields (minutes) — the scheduler already supported custom durations, only the UI was missing.
- WiFi Auto Detect: replaced blocking alert popups with an inline status line, highlights newly-detected devices in the device dropdown, and now retries with a wake-ping before giving up on a dozing device.
- Progress bar shows the run's actual end time and time remaining (e.g. `ends 7/23 14:00 (18h left)`), or `until study ends` in auto mode.
- Regression failures in the report now show the evidence screenshot filename next to the failure reason.
- Added a Mac-side `smoke.command` self-check (mirrors the existing Windows `smoke.bat`) so testers can verify a fresh install before their first real run.

### Fixed
- Web dashboard no longer shows a completed run as still "running" — the restore step that runs after `run_complete` was throwing off the running-state check.
- Fixed a latent bug where simply importing `web.app` (e.g. from an unrelated script) could trigger the process-exit cleanup and reset a *live* run's screen-timeout override — the cleanup hook is now only registered by the process that actually starts a run.

### Validation
- Python compile checks passed across all changed files.
- Android bounds-fallback navigation verified end-to-end on a Samsung SM-A325N (Android 11, different aspect ratio from the primary Pixel 7 test device) — 9/9 menu suite pass, fallback path confirmed to fire and succeed.
- Full regression suite (44 TCs) passed on Samsung hardware with the new navigation code.
- App study tracking verified live: a 24h study completing mid-run showed zero fake failures across 40 subsequent hourly skips, and a report correctly split injections into "within study window" vs. "after study end."
- `study_progress` verified across a full 0% → 100% study lifecycle overnight (16 samples).
- Web-server crash recovery verified by killing the server process mid-run and confirming the restarted server re-attached to the live run with full event history intact.
- Tester feedback from a completed 24h run informed three of the fixes above (ECG-check retry, Upload action notice, failure evidence filenames).

## [v1.1.1] — 2026-07-14 (updated 2026-07-15)

### Post-release update (2026-07-15)
- **BT-reconnect ECG check fixed for the current app layout**: the app main screen now uses Device Status / Real-time ECG tabs and has no `View` button on the default tab, so every check reported a misleading `View button not found`. The check now switches to the Real-time ECG tab and verifies `Live ECG Signal` directly (legacy View-button layout kept as fallback). Verified on Pixel 7 after both a scheduled BT test and a manual disconnect.
- **ECG Check web card no longer misleading**: only a real failure (`ECG signal not visible`) shows as `✗ No ECG`; skipped checks show `— Skipped` and inconclusive ones `~ Unverified`, with the reason and screenshot evidence (`on_main_screen`, `tab_switched`) recorded.
- **WiFi ADB Auto Detect finds every USB device**: previously only the first USB-connected device was detected/connected; now all are, with per-device errors reported. Cache file keeps the legacy single-device keys plus a new `devices` list.
- **Android menu-navigation robustness**: `Start Study` bottom-button coordinate fallback with warning logs (was silently swallowed), `open_menu` skips when already open, `close_menu` retries up to 4 times via the top-right close icon before falling back to Back. Verified with a 44/44 regression pass on Pixel 7.
- **iOS entrypoint docstring corrected**: it claimed BT/airplane tests were unavailable on iOS; they run via Control Center UI automation (`connectivity_ios`).

### Highlights
- Improved long-run stability for Android and iOS automation.
- Added stronger detection and recovery for scheduled Bluetooth disconnects, airplane mode transitions, app crashes, and Appium/WDA session loss during 24h+ soak tests.
- Improved reports so Android observed Bluetooth disconnects, scheduled BT/airplane tests, failed jobs, and regression-created diary entries are easier to distinguish.

### iOS Stability
- Changed iOS WDA handling to prefer a fresh WDA start by default, reducing failures caused by reusing stale WDA sessions.
- Clean up stale `iproxy`, `pymobiledevice3 usbmux forward`, and `pymobiledevice3 xcuitest` processes before starting WDA.
- Added explicit handling for `ECONNRESET`, `socket hang up`, `Session does not exist`, and proxy-command failures.
- Made iOS session recovery verify real WDA readiness with `get_window_size()` before reporting recovery success.
- Added up to 3 reconnect attempts when iOS session recovery is unstable immediately after WDA restart.
- Added session-aware retry for ratio-based coordinate taps, so iOS menu/navigation taps can recover from WDA session loss.
- Improved iOS health checks by attempting to navigate back to the main screen when `Log Symptoms` is not visible.

### Android Long-Run Reliability
- Added 30-second app crash monitoring with logcat evidence collection and automatic app relaunch.
- Added Android observed Bluetooth disconnect detection during long runs.
- Separated Android observed BT disconnects from scheduled BT/airplane tests.
- Removed Appium session contention between the monitor thread and scheduled jobs.
- Improved WiFi ADB reconnect fallback parsing.
- Limited USB re-enumeration waits to the cases where they are actually needed, reducing WiFi ADB recovery delays.
- Improved Bluetooth-off detection on Android 16 using stronger readout and polling logic.
- Strengthened session/UI recovery after airplane mode ends.

### Screen Timeout Safety
- Improved Android screen-timeout restoration after long runs.
- Restores the exact original screen timeout after normal stop, web stop, hard kill, or web-server restart when runtime evidence exists.
- Avoids treating an intentional 24h tester timeout as pollution.
- Deletes the saved original timeout file only after restore verification succeeds.

### Reports & Slack
- Added an Observed BT Disconnections report section with clearer separation between Android observed disconnects and scheduled tests.
- Records Bluetooth disconnect and reconnect timing more clearly.
- Shows failed scheduled jobs more clearly in HTML reports and Slack notifications.
- Records regression-created diary entries in the report.
- Tracks which symptom was involved when a symptom injection job fails.
- Improves ECG check diagnostics with clearer failure labels and round polling output.
- Improves report behavior for skip-regression runs.

### Artifacts & Diagnostics
- Fixed screenshot artifact handling so failed screenshot saves no longer leave fake paths in reports.
- Improved failure evidence collection around iOS/Android page source, screenshots, and logcat.
- Cleaned up runtime artifacts and misplaced screenshots so they do not pollute git state.

### Validation
- Python compile check passed.
- `scripts/smoke_test.py` passed.
- iOS skip-regression run confirmed: main screen reached, first symptom injection succeeded, Bluetooth OFF/ON completed, airplane mode completed, and the app reported `Disconnected` during the BT/airplane checks.

## [v1.1.0] — 2026-07-09

> v1.0.6으로 발행 준비되었던 릴리즈를 iOS 자동화 추가 규모를 반영해 v1.1.0으로 재버전


### Fixed
- **Windows에서 테스트 시작 즉시 크래시 ("Test failed — No time zone found with key America/Chicago")**: Windows에는 시스템 타임존 DB가 없어 APScheduler의 로컬 타임존 조회가 실패 → 런 전체 중단되던 문제 (테스터 리포트)
  - `requirements.txt`에 `tzdata` 추가 — 근본 수정 (`requirements.txt`)
  - 타임존 조회 실패 시에도 크래시 대신 UTC 폴백으로 스케줄러 계속 실행 (`src/scheduler.py`)
- **예기치 못한 인앱 오류 팝업으로 자동화 정지**: "Test failed" / "No time zone" 등 알 수 없는 오류 팝업 감지 시 증거 스크린샷 저장 후 자동 해제하고 진행 (`src/workflows/popup_handler.py`)
- **[iOS] 야간 시스템 알림으로 장기 실행 정지**: 'iOS 업데이트 설치되지 않음' 시스템 모달이 02~08시 모든 탭을 차단 → 주입/BT/airplane 6시간 연속 실패하던 문제. `autoDismissAlerts` capability + 팝업 핸들러의 시스템 알림 자동 해제 (`src/driver_ios.py`)
- **[iOS] 웹 실행 세션에서 BT 차단 사이클 스킵**: `App-Prefs:Bluetooth` 딥링크가 웹 생성 Appium 세션에서 동작하지 않아 BT 사이클이 통째로 건너뛰어지던 문제 — Settings 재실행 + Bluetooth 행 직접 탭 폴백, 실패 시 진단 스크린샷 저장 (`src/workflows/connectivity_ios.py`). 실기기 풀 사이클(BT 10분 + airplane 5분) 검증 완료
- **웹 기기 라벨 "Android" 하드코딩**: iOS run에서 대시보드/test report 기기명이 "iPhone14,4 Android"처럼 표시되던 문제 — iOS/Android 자동 구분 (`web/app.py`)
- **iOS 이벤트 대시보드 미표시**: iOS run이 emit하는 `*_ios` 이벤트를 정규화해 suite 카드·로그·진행률이 양 플랫폼에서 렌더되도록 수정 (`web/app.py`)
- **`--once` 단발 주입 NameError**: `ACTIVITIES` import 누락으로 dict catalog에서 즉사 — 장기 실행 경로 무영향 (`src/main.py`)
- **팀 허브 원격 iOS 세션 표시**: `*_ios` 이벤트 미정규화로 영원히 "running" + 기기/시간 빈칸이던 문제 (`web/app.py`)

### Added
- **[Beta] iOS 자동화 (Android 동등 기능)**: serial/menu/main/diary/menu-study regression 36 TC, go_to_main(BLE 연결·Study 시작), 시간별 symptom 주입, BT 차단(설정 앱 스위치 — 제어 센터 타일은 BLE 유지되어 부적합)·에어플레인 모드 테스트 (`src/*_ios.py`, `src/workflows/connectivity_ios.py`)
  - ⚠️ 검증 환경: iPhone 13 mini (iOS 18.6.2) 1대, 개발 Mac 한정. WDA 기기별 서명·설치 필요 — 테스터 배포 체계(사전 서명 WDA.ipa) 준비 중
- **웹 UI 플랫폼 선택**: Android/iOS 선택 → iOS 기기 목록(idevice_id) 표시, iOS run은 `main_ios.py`로 실행 (`web/app.py`, `web/templates/index.html`) — iOS는 상기 Beta 제약 동일
- **iOS 테스터 배포 파이프라인**: Mac 배포 ZIP에 iOS 지원 통합 — 사전 서명 WDA.ipa 자동 설치(등록 UDID 전용), `iproxy` 없으면 `pymobiledevice3` 폴백(brew 불필요), Developer Mode 안내. 관리자용 WDA.ipa 빌드 스크립트 포함 (`scripts/build_dist_bundle_mac.py`, `scripts/build_wda_ipa.sh`)
- **웹 UI run 중 설정 잠금**: 테스트 실행 중에는 설정 폼을 잠그고 안내 배너 표시 — 시작 시점에 확정되는 값을 mid-run에 바꿔도 반영되는 것처럼 보이던 혼동 방지. Stop / Inject Now / interval 변경은 계속 사용 가능 (`web/templates/index.html`)
- **iOS 앱 버그 리포트**: BT 상태 카드 UI 미갱신 (재현 조건·증적 포함, `docs/bug_reports/ios_bt_ui_sync_bug.txt`)
- **RN testID 요청 문서**: 좌표 기반 → element 기반 전환용 (`docs/testid_request_ios.txt`)
- **README 전면 개편 (영문)**: 플랫폼별 현황, 실행 흐름, regression 스위트 표, iOS Beta 상세, 배포 ZIP 가이드, 트러블슈팅
- **Windows Smoke CI**: main 푸시마다 GitHub Windows 러너에서 실제 배포 ZIP 빌드 → 번들 임베디드 Python으로 6종 스모크(타임존 DB·엔트리포인트 import·스케줄러·웹 부팅) — Windows 기기 없이 시작 크래시류 차단 (`.github/workflows/windows-smoke.yml`, `scripts/smoke_test.py`)
- **테스터용 `smoke.bat`**: Windows ZIP 루트 포함 — 압축 해제 후 더블클릭으로 30초 설치 자가 점검, 기기 불필요 (`smoke.bat`)

## [v1.0.5] — 2026-06-30

### Fixed
- **Symptom injection 미실행 버그**: `symptom_add_text` 설정값이 `"Add Diary"`로 되어 있어 UI health check가 항상 실패 → scheduler가 injection/BT disconnect/airplane mode 테스트를 전혀 시작하지 못하는 문제 수정 (`config/accurkardia.yaml`)
- **`check_connectivity` 오탐**: `on_main_screen` 판단을 `"Add Diary"` 하드코딩에서 config 기반 `symptom_add_text`로 변경 (`src/driver.py`)
- **`_try_add_diary_wifi_off` / `_try_add_diary_bt_off`**: 하드코딩된 `"Add Diary"` 제거, activity 섹션 제거 (AK 앱에 없음), submit 버튼을 config `log_symptoms_submit_text` ("Save") 로 변경 (`src/driver.py`)
- **`open_menu` 기기 호환성**: content-desc 탐색 대상 확장 ("Settings", "More options" 등), top-right 영역에서 `clickable=true` View/ImageView/ImageButton 탐색으로 좌표 의존도 감소 (`src/regression/helpers.py`)
- **`_is_menu_open` 인디케이터**: "Terms and Information", "Live Streaming", "Privacy", "About" 추가 (`src/regression/helpers.py`)
- **`open_menu` 진단**: 탭 직후 스크린샷(`open_menu_after_tap_N`) 추가 — 실패 원인 즉시 파악 가능
- **`go_to_main` 느린 디바이스 timeout 오탐**: BLE 연결이 120s를 약간 초과하는 느린 디바이스(예: SM-A325N)에서 실제로는 main screen에 도달했음에도 "Main screen not reached after 120s" 예외가 발생하던 문제 수정
  - 타임아웃 직후 screen을 재확인해 이미 main screen이면 성공으로 처리
  - loading overlay가 "Log Symptoms"를 가리는 동안에도 "My Study Progress" / "Device Status" 텍스트로 main screen 감지
  - `go_to_main` 진입 시 초기 체크도 3개 텍스트 모두 확인 (`src/regression/helpers.py`)

## [v1.0.0] — 2026-05-28

### Added
- **Battery card**: `battery_status` event 처리 추가 — 앱 화면에서 "Good"/"Low"/"Critical" 텍스트 감지 시 배터리 카드 실시간 업데이트 (`web/templates/index.html`, `src/driver.py`)
- **Field persistence**: serial number, Slack webhook을 localStorage에 저장 — 테스트 실행 중 새로고침해도 값 유지, 테스트 종료 시 자동 초기화 (`web/templates/index.html`)
- **Slack**: `slack_daily_report`, `slack_bug_report` 함수 추가 (`src/slack.py`)
- **symptom_inject**: `ACTIVITIES = []` export 추가 — run.py import 오류 수정 (`src/workflows/symptom_inject.py`)

### Fixed
- **Connectivity cards**: `bt_disconnect_done` 이벤트 발생 시 BT Signal / BT Diary / BT Reconnect / ECG Check 카드 모두 pass로 추론 표시
- **Connectivity cards**: `airplane_mode_done` 이벤트 발생 시 WiFi / WiFi Diary / WiFi Restore 카드 모두 pass로 추론 표시
- **Airplane mode**: Android 12+ (Pixel 7 등)에서 `settings put global airplane_mode_on` 명령이 권한 문제로 무시되던 버그 수정 → `adb shell cmd connectivity airplane-mode disable` 으로 교체 (`src/workflows/airplane_mode.py`)
- **WiFi ADB radio button ID conflict**: HTML form의 `id="conn-wifi"` 가 connectivity 카드 `id="conn-wifi"` 와 충돌하여 WiFi 카드가 업데이트 안 되던 버그 수정 → radio button ID를 `adb-usb` / `adb-wifi` 로 변경
- **go_to_main() Step 2/3 Continue tap**: `tap_text(contains=False)` + `@retry(tries=3)` 조합으로 ~37s 낭비 후 120s timeout 발생하던 문제 → `contains=True` 로 변경, pre-tap sleep 추가

## 2026-05-27 (earlier)

### Added
- **Real-time connectivity grid**: 웹 UI에 9개 connectivity 카드 추가 (Connection / BT Signal / BT Diary / BT Reconnect / ECG Check / WiFi / WiFi Diary / WiFi Restore / Battery)
- **HTML report**: Slack-style card layout으로 리디자인

### Fixed
- **BT disconnect workflow**: `check_connectivity()` 호출 추가 — BT 끊김/재연결 이벤트 감지 보강
- **Host sleep recovery**: injection chain 끊김 방지, web runner에 KeepAwake 추가

## 2026-05-22

### Fixed
- AK 앱 이미 측정 중일 때 BT reconnect spinner 상태에서도 측정 중 감지
- study 이미 활성화 상태로 재시작 시 serial/menu/signal regression 스킵
- AK main screen 감지 로직 수정, Connect 탭 보호
- Step 1에서 기기가 이미 등록된 경우 EditText 없는 케이스 처리
- BT disconnect / airplane mode 테스트 진행 중 symptom 주입 블락

## 2026-05-21

### Added
- **BT disconnect 주기 테스트**: 설정된 간격으로 BT를 끊고 재연결하는 주기 테스트
- **Airplane mode 주기 테스트**: 설정된 간격으로 airplane mode 활성화/비활성화 주기 테스트
- **Connectivity regression suite**: BT / WiFi 연결 상태 검증 테스트 스위트

### Fixed
- BT/airplane 주기 루프 순차 실행 보장, airplane mode 중 connectivity monitor 일시 중지

## 2026-05-15

### Fixed
- skip-regression 모드에서 connectivity 테스트 먼저 실행되도록 수정
- ADB WiFi keepalive 추가, stay_awake 옵션, scheduler misfire grace time 설정
- 웹 서버 포트 5002→5003 수정
- Python 설치 경로 자동 탐색 로직 보강

## 2026-05-13

### Fixed
- 주입 전 main screen 이동 네비게이션 보강
- 950 popup dismiss 로직 개선 (`Ok`/`OK` 목록 처리)
- WiFi ADB 연결 시 WiFi-off TC 스킵
