============================================================
  S-Patch AccurKardia Automation — macOS Guide
============================================================

[Prerequisites]
  1. AccurKardia app must be in an active study state.
     ("My Study Progress" screen must be visible)
  2. Connect your Android device via USB and enable USB Debugging.
     (Settings → Developer options → USB Debugging)
  3. Tap "Allow" on the "Allow USB Debugging" popup on the device.

------------------------------------------------------------
[First Time — Installation]

  Double-click install.command

  The following will be installed automatically:
    - Homebrew
    - Python 3.10+
    - Node.js / npm
    - ADB (android-platform-tools)
    - Appium
    - UiAutomator2 driver
    - Python packages (requirements.txt)

  Enter your Mac password if prompted and press Enter.
  Wait until the installation complete message appears.

------------------------------------------------------------
[Launch]

  Double-click run.command

  - Appium server starts automatically.
  - Browser opens automatically (http://127.0.0.1:5002).
  - Keep this terminal window OPEN during the test.

  In the browser:
    1. Select your device
    2. Enter the S-Patch serial number
    3. Set duration and injection interval
    4. Click "Start Test"

------------------------------------------------------------
[Stop]

  Double-click STOP.command
  or press Ctrl+C in the run.command window.

------------------------------------------------------------
[Troubleshooting]

  1. Re-run install.command.
  2. Check log at /tmp/ak_install_*.log
  3. Reconnect USB cable and retry.

============================================================
