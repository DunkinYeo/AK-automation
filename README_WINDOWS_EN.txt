============================================================
  S-Patch AccurKardia Automation  —  Windows Guide
============================================================

This tool automates Regression testing and long-run
symptom injection (Log Symptoms) for the AccurKardia app.
No development knowledge required.

Sleep prevention is active during the test run.


------------------------------------------------------------
  Before You Start — Unblock the ZIP File
------------------------------------------------------------

ZIP files received via email or shared folders may be
blocked by Windows security policy.

How to unblock:
  1) Right-click the ZIP file
  2) Select [Properties]
  3) Check [Unblock] at the bottom if visible, then click [OK]
  4) Extract the ZIP and proceed

※ Skipping this step may cause errors when running install.bat.


------------------------------------------------------------
  1. First-Time Installation
------------------------------------------------------------

  1) Connect your Android phone to the PC via USB cable.

  2) Enable USB Debugging on the phone:
       Settings → About phone → Software information
       → Tap [Build number] 7 times quickly
       Settings → Developer options → USB Debugging ON

  3) Tap [Allow] on the "Allow USB Debugging?" popup on the device.

  4) Double-click install.bat.
     Python, Node.js, ADB, Appium, and Python packages
     will be installed automatically.

  ※ First installation may take 5–10 minutes.
  ※ If the CMD window seems frozen, press Enter once.
  ※ If "Windows protected your PC" appears,
     click [More info] → [Run anyway].


------------------------------------------------------------
  2. Running the Test
------------------------------------------------------------

  1) Verify that a study has been registered in the AccurKardia web system.

  2) Connect your Android device via USB.

  3) Double-click run.bat.
     The browser opens automatically after a few seconds.
     If not, open manually:  http://127.0.0.1:5003

  4) Configure in the browser:
     - Device              : Select the connected device
     - S-Patch Serial No.  : Enter the S-Patch serial number (required)
     - Test Name           : Enter a test name
     - Test Duration       : Set total test duration
     - Injection Interval  : Set symptom injection interval
     - Skip Regression     : Check if the study is already in progress (see below)
     - Slack Webhook URL   : Optional Slack notifications

  5) Click [Start Test].

  ─ Normal mode (Skip Regression unchecked):
       Runs all Regression tests before the study starts.
       (serial → menu → main → diary → menu-study → connectivity)
       Symptom injection schedule starts after Regression completes.

  ─ Skip Regression mode (study already in progress):
       Skips serial / menu / main / diary / menu-study Regression.
       Runs Connectivity tests + symptom injection on the active study app.

  6) Keep the run.bat window OPEN during the test.


------------------------------------------------------------
  3. Stopping the Test
------------------------------------------------------------

  Double-click STOP.bat or close the run.bat window.


------------------------------------------------------------
  4. Troubleshooting
------------------------------------------------------------

  Device not detected:
    - Unplug and replug the USB cable.
    - Verify USB Debugging is enabled.
    - Tap [Allow] on any popup on the device screen.

  install.bat errors:
    - Re-run install.bat (most issues resolve on retry).
    - If "Windows protected your PC" appears:
      click [More info] → [Run anyway].
    - If Python is installed but install.bat still fails:
      Python may have been installed without the "Add to PATH" option.
      install.bat will automatically search common install locations.
      If it still fails, run the following manually in CMD:
        .venv\Scripts\activate
        pip install -r requirements.txt
      Then launch run.bat.

  Script appears frozen:
    - Press Enter once or twice.

  Browser doesn't open:
    - Navigate to http://127.0.0.1:5003 manually.

  Files blocked after ZIP extraction:
    - Right-click the ZIP → Properties → check [Unblock] → re-extract.
    - Or add the extracted folder to Windows Defender exclusions.


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
