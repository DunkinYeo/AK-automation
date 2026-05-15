============================================================
  S-Patch AccurKardia Automation  —  macOS Guide
============================================================

This tool automates Regression testing and long-run
symptom injection (Log Symptoms) for the AccurKardia app.
No development knowledge required.

Sleep prevention is active during the test run.
(Uses caffeinate — AC power recommended for long runs)


------------------------------------------------------------
  Before You Start — Grant Execution Permission
------------------------------------------------------------

macOS may show "Cannot be opened because the developer
cannot be verified" when double-clicking .command files.

Fix options:
  Option 1) Right-click the file → select [Open]
  Option 2) Run in Terminal:
               chmod +x install.command run.command STOP.command
  Option 3) Remove quarantine flag in Terminal:
               xattr -d com.apple.quarantine install.command run.command STOP.command


------------------------------------------------------------
  1. First-Time Installation
------------------------------------------------------------

  1) Connect your Android phone to the Mac via USB cable.

  2) Enable USB Debugging on the phone:
       Settings → About phone → Software information
       → Tap [Build number] 7 times quickly
       Settings → Developer options → USB Debugging ON

  3) Tap [Allow] on the "Allow USB Debugging?" popup on the device.

  4) Double-click install.command in Finder.
     Homebrew, Python, Node.js, ADB, Appium, and Python
     packages will be installed automatically.

  ※ First installation may take 5–10 minutes.
  ※ Enter your Mac login password if prompted.
     (Not shown on screen — this is normal)


------------------------------------------------------------
  2. Running the Test
------------------------------------------------------------

  1) Make sure the AccurKardia app is in an active study state.
     ("My Study Progress" screen must be visible)

  2) Connect your Android device via USB.

  3) Double-click run.command in Finder.
     The browser opens automatically after a few seconds.
     If not, open manually:  http://127.0.0.1:5003

  4) Configure in the browser:
     - Device              : Select the connected device
     - S-Patch Serial No.  : Enter the S-Patch serial number (required)
     - Test Name           : Enter a test name
     - Test Duration       : Set total test duration
     - Injection Interval  : Set symptom injection interval
     - Skip Regression     : Check if study is already active (see below)
     - Slack Webhook URL   : Optional Slack notifications

  5) Click [Start Test].

  ─ Normal mode (Skip Regression unchecked):
       1. Regression tests (main → diary → menu-study)
       2. Symptom injection schedule starts

  ─ Skip Regression mode (study already active):
       Skips Regression and starts symptom injection immediately.

  6) Keep the terminal window OPEN during the test.


------------------------------------------------------------
  3. Stopping the Test
------------------------------------------------------------

  Double-click STOP.command
  or press Ctrl+C in the run.command window.


------------------------------------------------------------
  4. Troubleshooting
------------------------------------------------------------

  Device not detected:
    - Unplug and replug the USB cable.
    - Verify USB Debugging is enabled.
    - Tap [Allow] on any popup on the device screen.

  .command file won't open:
    - Right-click → [Open].
    - Or in Terminal:
        chmod +x install.command run.command STOP.command

  Blocked by macOS security:
    - In Terminal:
        xattr -d com.apple.quarantine install.command run.command STOP.command

  Browser doesn't open:
    - Navigate to http://127.0.0.1:5003 manually.

  Password requested during install:
    - Enter your Mac login password (not shown on screen — normal).

  Sleep prevention not working:
    - Connect Mac to AC power (charger).


------------------------------------------------------------
  5. Full TC List (Active study required)
------------------------------------------------------------

  [Main Screen — 5 TCs]
  TC-MAIN-001   My Study Progress / Device Status tab visible
  TC-MAIN-002   Network / Bluetooth / Battery cards visible
  TC-MAIN-003   Log Symptoms button visible and enabled
  TC-MAIN-004   Real-time ECG tab → Live ECG Signal visible
  TC-MAIN-005   Back → returns to main screen

  [Log Symptoms / Diary — 5 TCs]
  TC-DIARY-001   Log Symptoms → sheet opens, Symptom section visible
  TC-DIARY-002   Full symptom list displayed
  TC-DIARY-003   Select symptom → Save → returns to main screen
  TC-DIARY-004   X button → sheet closes, returns to main screen
  TC-DIARY-005   No symptom selected → Save button state check

  [Menu Study — 5 TCs]
  TC-MENU-STUDY-001   Study menu → Device Information visible
  TC-MENU-STUDY-002   Study menu → Study Information item visible
  TC-MENU-STUDY-003   Study menu section items displayed correctly
  TC-MENU-STUDY-004   Study Information tap → study info screen
  TC-MENU-STUDY-005   Device Information tap → device info screen

============================================================
