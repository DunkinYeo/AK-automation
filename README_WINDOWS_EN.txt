============================================================
  S-Patch AccurKardia Automation — Windows Guide
============================================================

[Prerequisites]
  1. AccurKardia app must be in an active study state.
     ("My Study Progress" screen must be visible)
  2. Connect your Android device via USB and enable USB Debugging.
     (Settings → Developer options → USB Debugging)
  3. Tap "Allow" on the "Allow USB Debugging" popup on the device.

------------------------------------------------------------
[First Time — Installation]

  Double-click install.bat
  (If a security warning appears: click "More info" → "Run anyway")

  The following will be installed automatically:
    - Python 3.12 (auto-installed via winget if missing)
    - Node.js LTS (auto-installed if missing)
    - ADB (platform-tools downloaded automatically)
    - Appium
    - UiAutomator2 driver
    - Python packages (requirements.txt)

  Wait until the installation complete message appears.
  If errors occur, try running install.bat as Administrator.

------------------------------------------------------------
[Launch]

  Double-click run.bat

  - Appium server starts in a separate window.
  - Browser opens automatically (http://127.0.0.1:5002).
  - Keep the run.bat window OPEN during the test.

  In the browser:
    1. Select your device
    2. Enter the S-Patch serial number
    3. Set duration and injection interval
    4. Click "Start Test"

------------------------------------------------------------
[Stop]

  Double-click STOP.bat or close the run.bat window.

------------------------------------------------------------
[Troubleshooting]

  1. Run install.bat as Administrator.
  2. Check log at %TEMP%\ak_install.log
  3. Reconnect USB cable and retry.
  4. Add the folder to antivirus exclusions if blocked.

============================================================
