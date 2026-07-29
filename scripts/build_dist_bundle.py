"""
Build standalone Windows ZIP with bundled Python, Node.js, and ADB.
Appium is installed on first run using bundled Node.js (~1-2 min, one-time only).

Creates:
  AccurKardia-Windows-Standalone-v{VERSION}-{TODAY}.zip  (~100MB)

Usage:
  python scripts/build_dist_bundle.py
  python scripts/build_dist_bundle.py --out ~/Desktop
"""

import argparse
import datetime
import io
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today().strftime("%Y%m%d")
VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "0.0.0"

PYTHON_VERSION = "3.13.2"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"

NODE_VERSION = "22.13.1"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip"

ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
ADB_FILES = {"platform-tools/adb.exe", "platform-tools/AdbWinApi.dll", "platform-tools/AdbWinUsbApi.dll"}

SKIP_PACKAGES = {"black", "ruff", "pre-commit", "pytest"}  # dev-only, not needed at runtime

RUN_BAT = r"""@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

SET "A=%CD%\automation"
SET "PY=%A%\python\python.exe"
SET "NODE=%A%\node"
SET "ADB=%A%\runtime\platform-tools"
SET "APPIUM_INSTALL=%A%\appium"
SET "APPIUM_HOME=%A%\appium_home"
SET "_APPIUM_CMD_BIN=%APPIUM_INSTALL%\appium.cmd"
SET "_APPIUM_CMD_NM=%APPIUM_INSTALL%\node_modules\.bin\appium.cmd"
SET "_APPIUM_CMD="
SET "LOG=%TEMP%\ak_run.log"
SET "APPIUM_LOG=%TEMP%\ak_appium.log"
SET "WEB_LOG=%TEMP%\ak_web.log"

SET "ANDROID_HOME=%A%\runtime"
SET "ANDROID_SDK_ROOT=%A%\runtime"
SET "PATH=%ADB%;%NODE%;%PATH%"
SET "PYTHONPATH=%A%"

IF NOT EXIST "%APPIUM_HOME%" mkdir "%APPIUM_HOME%"

echo AccurKardia run started %DATE% %TIME% > "%LOG%"
echo [INIT] Variables set >> "%LOG%"

echo.
echo   +==============================================+
echo   ^|   AccurKardia -- Starting (Standalone)     ^|
echo   +==============================================+
echo.
echo   Log: %LOG%
echo.

REM ── Check if already running (port 5003) ────────────────────────────────────────
netstat -ano 2>nul | findstr ":5003 " | findstr "LISTENING" >nul
IF NOT ERRORLEVEL 1 (
    echo   AccurKardia is already running.
    start http://localhost:5003
    pause & EXIT /B 0
)

REM ── System prep (all silently suppressed) ────────────────────────────────────────
powershell -NoProfile -WindowStyle Hidden -Command ^
  "Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled 1 -ErrorAction SilentlyContinue" >nul 2>&1
powershell -NoProfile -WindowStyle Hidden -Command ^
  "Get-ChildItem '%A%' -Recurse | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
powershell -NoProfile -WindowStyle Hidden -Command ^
  "Add-MpPreference -ExclusionPath '%A%' -ErrorAction SilentlyContinue" >nul 2>&1

REM ════════════════════════════════════════════════════════════════════
REM [1/5] Java
REM ════════════════════════════════════════════════════════════════════
echo   [1/5] Checking Java...
echo [1/5] START >> "%LOG%"

REM Skip scan if JAVA_HOME already valid
SET "_JAVA_OK=0"
IF NOT "%JAVA_HOME%"=="" IF EXIST "%JAVA_HOME%\bin\java.exe" SET "_JAVA_OK=1"
IF "!_JAVA_OK!"=="1" GOTO :java_verify

REM Scan PATH
SET "_JAVA_FOUND=0"
FOR /F "tokens=*" %%J IN ('where java 2^>nul') DO (
    IF "!_JAVA_FOUND!"=="0" (
        FOR %%P IN ("%%~dpJ..") DO (
            IF "!_JAVA_FOUND!"=="0" (
                IF EXIST "%%~fP\bin\java.exe" (
                    SET "JAVA_HOME=%%~fP"
                    SET "_JAVA_FOUND=1"
                )
            )
        )
    )
)
IF "!_JAVA_FOUND!"=="1" GOTO :java_verify

REM Scan common install locations
SET "_JAVA_FOUND=0"
FOR %%B IN (
    "%ProgramFiles%\Eclipse Adoptium"
    "%ProgramFiles%\Java"
    "%ProgramFiles%\Microsoft"
    "%ProgramFiles%\OpenJDK"
    "%ProgramFiles(x86)%\Java"
) DO (
    IF "!_JAVA_FOUND!"=="0" (
        FOR /D %%D IN ("%%~B\jdk*" "%%~B\jre*") DO (
            IF "!_JAVA_FOUND!"=="0" (
                IF EXIST "%%D\bin\java.exe" (
                    SET "JAVA_HOME=%%D"
                    SET "_JAVA_FOUND=1"
                )
            )
        )
    )
)
IF "!_JAVA_FOUND!"=="1" GOTO :java_verify

REM Try winget (output to log to avoid localized console text)
echo   Java not found. Trying winget (output to log)...
echo [1/5] winget start >> "%LOG%"
SET "_WINGET_OK=0"
FOR %%P IN (
    "Microsoft.OpenJDK.21"
    "EclipseAdoptium.Temurin.21.JRE"
    "EclipseAdoptium.Temurin.21.JDK"
) DO (
    IF "!_WINGET_OK!"=="0" (
        winget install --id %%P --scope user --silent ^
          --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
        IF NOT ERRORLEVEL 1 SET "_WINGET_OK=1"
        IF "!_WINGET_OK!"=="0" (
            winget install --id %%P --silent ^
              --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
            IF NOT ERRORLEVEL 1 SET "_WINGET_OK=1"
        )
    )
)
SET "_JAVA_FOUND=0"
FOR %%B IN (
    "%ProgramFiles%\Microsoft"
    "%ProgramFiles%\Eclipse Adoptium"
    "%LOCALAPPDATA%\Microsoft"
    "%LOCALAPPDATA%\Programs\Eclipse Adoptium"
) DO (
    IF "!_JAVA_FOUND!"=="0" (
        FOR /D %%D IN ("%%~B\jdk*" "%%~B\jre*") DO (
            IF "!_JAVA_FOUND!"=="0" (
                IF EXIST "%%D\bin\java.exe" (
                    SET "JAVA_HOME=%%D"
                    SET "_JAVA_FOUND=1"
                )
            )
        )
    )
)
IF "!_JAVA_FOUND!"=="1" GOTO :java_verify

REM Portable JRE fallback
SET "_JRE_DIR=%A%\jre"
SET "_JRE_ZIP=%TEMP%\ak_jre.zip"
SET "_JRE_URL=https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse"

echo   winget unavailable. Downloading portable JRE. Please wait...
echo [1/5] JRE download start >> "%LOG%"
powershell -NoProfile -Command ^
  "try { Invoke-WebRequest -Uri '%_JRE_URL%' -OutFile '%_JRE_ZIP%' -UseBasicParsing -TimeoutSec 180; exit 0 } catch { Write-Output ('JRE download error: ' + $_.Exception.Message); exit 1 }" >> "%LOG%" 2>&1
SET "_PS_EXIT=!ERRORLEVEL!"
IF "!_PS_EXIT!"=="" SET "_PS_EXIT=unknown"
echo   JRE download completed (exit: !_PS_EXIT!^).
echo [1/5] JRE download exit: !_PS_EXIT! >> "%LOG%"
IF NOT "!_PS_EXIT!"=="0" (
    echo.
    echo   ERROR  Portable JRE download failed (exit code: !_PS_EXIT!^).
    echo          Log: %LOG%
    echo [1/5] FAIL: JRE download >> "%LOG%"
    pause
    EXIT /B 1
)
IF NOT EXIST "%_JRE_ZIP%" (
    echo.
    echo   ERROR  Portable JRE download failed (file not created^).
    echo          Log: %LOG%
    echo [1/5] FAIL: JRE zip missing >> "%LOG%"
    pause
    EXIT /B 1
)

echo   Extracting portable JRE...
echo [1/5] JRE extract start >> "%LOG%"
powershell -NoProfile -Command ^
  "try { Expand-Archive -Path '%_JRE_ZIP%' -DestinationPath '%_JRE_DIR%' -Force; Remove-Item '%_JRE_ZIP%' -ErrorAction SilentlyContinue; exit 0 } catch { Write-Output ('JRE extract error: ' + $_.Exception.Message); exit 1 }" >> "%LOG%" 2>&1
SET "_PS_EXIT=!ERRORLEVEL!"
IF "!_PS_EXIT!"=="" SET "_PS_EXIT=unknown"
echo   JRE extraction completed (exit: !_PS_EXIT!^).
echo [1/5] JRE extract exit: !_PS_EXIT! >> "%LOG%"
IF NOT "!_PS_EXIT!"=="0" (
    echo.
    echo   ERROR  Portable JRE extraction failed (exit code: !_PS_EXIT!^).
    echo          Log: %LOG%
    echo [1/5] FAIL: JRE extract >> "%LOG%"
    pause
    EXIT /B 1
)
echo   Portable JRE installed OK.

SET "_JAVA_FOUND=0"
FOR /D %%D IN ("%_JRE_DIR%\jdk*") DO (
    IF "!_JAVA_FOUND!"=="0" (
        IF EXIST "%%D\bin\java.exe" (
            SET "JAVA_HOME=%%D"
            SET "_JAVA_FOUND=1"
        )
    )
)
FOR /D %%D IN ("%_JRE_DIR%\jre*") DO (
    IF "!_JAVA_FOUND!"=="0" (
        IF EXIST "%%D\bin\java.exe" (
            SET "JAVA_HOME=%%D"
            SET "_JAVA_FOUND=1"
        )
    )
)
IF "!_JAVA_FOUND!"=="1" GOTO :java_verify

echo.
echo   ERROR  Java could not be installed automatically.
echo          Please install manually: https://adoptium.net
echo          Then re-run run.bat.
echo.
echo [1/5] FAIL: java.exe not found >> "%LOG%"
pause
EXIT /B 1

:java_verify
SET "PATH=%JAVA_HOME%\bin;%PATH%"
IF NOT EXIST "%JAVA_HOME%\bin\java.exe" (
    echo.
    echo   ERROR  java.exe not found at: %JAVA_HOME%\bin\java.exe
    echo          Log: %LOG%
    echo [1/5] FAIL: java.exe missing at JAVA_HOME >> "%LOG%"
    pause
    EXIT /B 1
)
echo   Java OK: %JAVA_HOME%
echo [1/5] OK: %JAVA_HOME% >> "%LOG%"
echo [1/5] -> Entering [2/5] Appium >> "%LOG%"

REM ════════════════════════════════════════════════════════════════════
REM [2/5] Appium
REM ════════════════════════════════════════════════════════════════════
echo.
echo   [2/5] Checking Appium...
echo [2/5] START >> "%LOG%"

IF NOT EXIST "%NODE%\node.exe" (
    echo.
    echo   ERROR  Bundled Node.js not found: %NODE%\node.exe
    echo          The standalone package may be corrupted.
    echo          Log: %LOG%
    echo [2/5] FAIL: node.exe missing >> "%LOG%"
    pause
    EXIT /B 1
)
IF NOT EXIST "%NODE%\npm.cmd" (
    echo.
    echo   ERROR  Bundled npm not found: %NODE%\npm.cmd
    echo          The standalone package may be corrupted.
    echo          Log: %LOG%
    echo [2/5] FAIL: npm.cmd missing >> "%LOG%"
    pause
    EXIT /B 1
)
echo [2/5] node.exe: %NODE%\node.exe >> "%LOG%"
echo [2/5] npm.cmd:  %NODE%\npm.cmd >> "%LOG%"

REM Resolve: bin > node_modules\.bin > recursive search
SET "_APPIUM_CMD="
IF EXIST "%_APPIUM_CMD_BIN%" SET "_APPIUM_CMD=%_APPIUM_CMD_BIN%"
IF "%_APPIUM_CMD%"=="" IF EXIST "%_APPIUM_CMD_NM%" SET "_APPIUM_CMD=%_APPIUM_CMD_NM%"
IF "%_APPIUM_CMD%"=="" (
    FOR /F "delims=" %%F IN ('dir /b /s "%APPIUM_INSTALL%\appium.cmd" 2^>nul') DO (
        IF "!_APPIUM_CMD!"=="" SET "_APPIUM_CMD=%%F"
    )
)

IF NOT "%_APPIUM_CMD%"=="" (
    echo   Appium already installed.
    echo [2/5] Appium present: %_APPIUM_CMD% >> "%LOG%"
) ELSE (
    echo   Installing Appium. This may take a few minutes...
    echo [2/5] npm install start >> "%LOG%"
    call "%NODE%\npm.cmd" install -g appium --prefix "%APPIUM_INSTALL%" --quiet --no-progress >> "%LOG%" 2>&1
    SET "_NPM_EXIT=!ERRORLEVEL!"
    IF "!_NPM_EXIT!"=="" SET "_NPM_EXIT=unknown"
    echo   npm install completed (exit code: !_NPM_EXIT!^).
    echo [2/5] npm exit: !_NPM_EXIT! >> "%LOG%"

    SET "_APPIUM_CMD="
    IF EXIST "%_APPIUM_CMD_BIN%" SET "_APPIUM_CMD=%_APPIUM_CMD_BIN%"
    IF "!_APPIUM_CMD!"=="" IF EXIST "%_APPIUM_CMD_NM%" SET "_APPIUM_CMD=%_APPIUM_CMD_NM%"
    IF "!_APPIUM_CMD!"=="" (
        FOR /F "delims=" %%F IN ('dir /b /s "%APPIUM_INSTALL%\appium.cmd" 2^>nul') DO (
            IF "!_APPIUM_CMD!"=="" SET "_APPIUM_CMD=%%F"
        )
    )

    IF NOT "!_APPIUM_CMD!"=="" (
        echo   Appium installed OK.
        echo [2/5] Appium installed: !_APPIUM_CMD! >> "%LOG%"
    ) ELSE (
        echo.
        echo   ERROR  Appium installation failed.
        echo          npm exit code: !_NPM_EXIT!
        echo          appium.cmd not found in: %APPIUM_INSTALL%
        echo          Log: %LOG%
        echo [2/5] FAIL: appium.cmd missing. npm exit: !_NPM_EXIT! >> "%LOG%"
        pause
        EXIT /B 1
    )
)
echo   Appium command: !_APPIUM_CMD!
echo [2/5] OK: !_APPIUM_CMD! >> "%LOG%"
echo [2/5] -> Entering [3/5] UiAutomator2 >> "%LOG%"

REM ════════════════════════════════════════════════════════════════════
REM [3/5] UiAutomator2
REM ════════════════════════════════════════════════════════════════════
echo.
echo   [3/5] Checking UiAutomator2 driver...
echo [3/5] START >> "%LOG%"
echo [3/5] _APPIUM_CMD: !_APPIUM_CMD! >> "%LOG%"

REM Pre-check: Appium command must exist
IF NOT EXIST "!_APPIUM_CMD!" (
    echo.
    echo   ERROR  Appium command not found: !_APPIUM_CMD!
    echo          Log: %LOG%
    echo [3/5] FAIL: _APPIUM_CMD not found >> "%LOG%"
    pause
    EXIT /B 1
)

REM Define BOTH temp files at top level (outside any block) so %var% expansion works
SET "_DRV_TMP=%TEMP%\ak_drv_list.txt"
SET "_DRV_TMP2=%TEMP%\ak_drv_verify.txt"
echo [3/5] _DRV_TMP:  %_DRV_TMP% >> "%LOG%"
echo [3/5] _DRV_TMP2: %_DRV_TMP2% >> "%LOG%"

echo   Running: appium driver list --installed
echo [3/5] CMD: call "!_APPIUM_CMD!" driver list --installed >> "%LOG%"
call "!_APPIUM_CMD!" driver list --installed > "%_DRV_TMP%" 2>&1
SET "_LST_EXIT=!ERRORLEVEL!"
IF "!_LST_EXIT!"=="" SET "_LST_EXIT=unknown"
echo   Driver list completed (exit code: !_LST_EXIT!^).
echo [3/5] driver list exit: !_LST_EXIT! >> "%LOG%"

IF NOT EXIST "%_DRV_TMP%" (
    echo.
    echo   ERROR  Driver list output file not created: %_DRV_TMP%
    echo          Log: %LOG%
    echo [3/5] FAIL: driver list output file missing >> "%LOG%"
    pause
    EXIT /B 1
)
type "%_DRV_TMP%" >> "%LOG%" 2>nul

IF NOT "!_LST_EXIT!"=="0" (
    echo.
    echo   ERROR  appium driver list failed (exit code: !_LST_EXIT!^).
    echo          Appium command: !_APPIUM_CMD!
    echo          Log: %LOG%
    echo [3/5] FAIL: driver list exit !_LST_EXIT! >> "%LOG%"
    del "%_DRV_TMP%" >nul 2>&1
    pause
    EXIT /B 1
)

echo   Searching for uiautomator2 in driver list output...
findstr /I "uiautomator2" "%_DRV_TMP%" >nul 2>&1
SET "_FIND_EXIT=!ERRORLEVEL!"
IF "!_FIND_EXIT!"=="" SET "_FIND_EXIT=unknown"
del "%_DRV_TMP%" >nul 2>&1
echo [3/5] findstr exit: !_FIND_EXIT! >> "%LOG%"

IF "!_FIND_EXIT!"=="0" (
    echo   UiAutomator2 driver already installed.
    echo [3/5] UiAutomator2 present >> "%LOG%"
) ELSE (
    echo   UiAutomator2 not found. Installing...
    echo   Installing UiAutomator2 driver. This may take a few minutes...
    echo [3/5] CMD: call "!_APPIUM_CMD!" driver install uiautomator2 >> "%LOG%"
    call "!_APPIUM_CMD!" driver install uiautomator2 >> "%LOG%" 2>&1
    SET "_DRV_INST_EXIT=!ERRORLEVEL!"
    IF "!_DRV_INST_EXIT!"=="" SET "_DRV_INST_EXIT=unknown"
    echo   UiAutomator2 install completed (exit code: !_DRV_INST_EXIT!^).
    echo [3/5] driver install exit: !_DRV_INST_EXIT! >> "%LOG%"

    echo   Verifying UiAutomator2 driver...
    echo [3/5] _APPIUM_CMD at verify: !_APPIUM_CMD! >> "%LOG%"
    echo [3/5] _DRV_TMP2 at verify: !_DRV_TMP2! >> "%LOG%"
    echo [3/5] CMD: call "!_APPIUM_CMD!" driver list --installed >> "%LOG%"
    call "!_APPIUM_CMD!" driver list --installed > "!_DRV_TMP2!" 2>&1
    SET "_VRFY_EXIT=!ERRORLEVEL!"
    IF "!_VRFY_EXIT!"=="" SET "_VRFY_EXIT=unknown"
    echo   Verification completed (exit code: !_VRFY_EXIT!^).
    echo [3/5] verify list exit: !_VRFY_EXIT! >> "%LOG%"

    IF EXIST "!_DRV_TMP2!" (
        type "!_DRV_TMP2!" >> "%LOG%" 2>nul
        findstr /I "uiautomator2" "!_DRV_TMP2!" >nul 2>&1
        SET "_FIND2_EXIT=!ERRORLEVEL!"
        IF "!_FIND2_EXIT!"=="" SET "_FIND2_EXIT=unknown"
        del "!_DRV_TMP2!" >nul 2>&1
        echo [3/5] verify findstr exit: !_FIND2_EXIT! >> "%LOG%"
    ) ELSE (
        echo   WARN  Verify output file not created: !_DRV_TMP2!
        echo [3/5] WARN: verify output file missing >> "%LOG%"
        SET "_FIND2_EXIT=1"
    )

    IF NOT "!_FIND2_EXIT!"=="0" (
        echo.
        echo   ERROR  UiAutomator2 driver not found after installation.
        echo          Appium command:    !_APPIUM_CMD!
        echo          Install exit code: !_DRV_INST_EXIT!
        echo          Verify exit code:  !_VRFY_EXIT!
        echo          Log: %LOG%
        echo [3/5] FAIL: UiAutomator2 missing after install. inst=!_DRV_INST_EXIT! vrfy=!_VRFY_EXIT! >> "%LOG%"
        pause
        EXIT /B 1
    )
    echo   UiAutomator2 driver installed OK.
    echo [3/5] UiAutomator2 installed OK >> "%LOG%"
)
echo [3/5] -> Entering [4/5] ADB >> "%LOG%"

REM ════════════════════════════════════════════════════════════════════
REM [4/5] ADB
REM ════════════════════════════════════════════════════════════════════
echo.
echo   [4/5] Checking ADB...
echo [4/5] START >> "%LOG%"

IF NOT EXIST "%ADB%\adb.exe" (
    echo.
    echo   ERROR  adb.exe not found: %ADB%\adb.exe
    echo          Antivirus may have removed it or the package is corrupted.
    echo.
    echo   Fix: Add this folder to your antivirus exclusion list and re-run:
    echo      %A%
    echo.
    echo          Log: %LOG%
    echo [4/5] FAIL: adb.exe not found >> "%LOG%"
    pause
    EXIT /B 1
)

echo   Running: adb version
echo [4/5] adb version start >> "%LOG%"
"%ADB%\adb.exe" version >> "%LOG%" 2>&1
SET "_ADB_EXIT=!ERRORLEVEL!"
IF "!_ADB_EXIT!"=="" SET "_ADB_EXIT=unknown"
echo   ADB completed (exit code: !_ADB_EXIT!^).
echo [4/5] adb exit: !_ADB_EXIT! >> "%LOG%"
IF NOT "!_ADB_EXIT!"=="0" (
    echo.
    echo   ERROR  adb.exe cannot be executed (exit code: !_ADB_EXIT!^).
    echo          Your antivirus may have quarantined it.
    echo.
    echo   Fix: Add this folder to your antivirus exclusion list and re-run:
    echo      %A%
    echo.
    echo          Log: %LOG%
    echo [4/5] FAIL: adb exit !_ADB_EXIT! >> "%LOG%"
    pause
    EXIT /B 1
)
echo   ADB OK.
echo [4/5] OK >> "%LOG%"

echo   Starting ADB server...
"%ADB%\adb.exe" start-server >> "%LOG%" 2>&1
echo   Detecting connected devices...
"%ADB%\adb.exe" devices >> "%LOG%" 2>&1
echo [4/5] adb devices done >> "%LOG%"

echo [4/5] -> Entering [5/5] Appium + web server >> "%LOG%"

REM ════════════════════════════════════════════════════════════════════
REM [5/5] Start Appium + web server
REM ════════════════════════════════════════════════════════════════════
echo.
echo   [5/5] Starting services...
echo [5/5] START >> "%LOG%"

IF NOT EXIST "%PY%" (
    echo.
    echo   ERROR  Bundled Python not found: %PY%
    echo          The standalone package may be corrupted.
    echo          Log: %LOG%
    echo [5/5] FAIL: python.exe missing >> "%LOG%"
    pause
    EXIT /B 1
)
echo [5/5] Python OK: %PY% >> "%LOG%"

echo   Starting Appium server...
echo [5/5] Appium launch start >> "%LOG%"
echo [5/5] Appium log: %APPIUM_LOG% >> "%LOG%"
echo @echo off > "%TEMP%\ak_appium.bat"
echo call "!_APPIUM_CMD!" --relaxed-security ^>^> "%APPIUM_LOG%" 2^>^&1 >> "%TEMP%\ak_appium.bat"
start "AK - Appium" /B cmd /c "%TEMP%\ak_appium.bat"
echo [5/5] Appium process launched >> "%LOG%"

echo   Waiting for Appium on port 4723 (up to 30s^)...
SET "_APPIUM_READY=0"
FOR /L %%i IN (1,1,15) DO (
    IF !_APPIUM_READY!==0 (
        powershell -NoProfile -Command ^
          "try{if((Invoke-WebRequest 'http://localhost:4723/status' -TimeoutSec 1 -UseBasicParsing).StatusCode -eq 200){exit 0}else{exit 1}}catch{exit 1}" >nul 2>&1
        IF NOT ERRORLEVEL 1 SET _APPIUM_READY=1
        IF !_APPIUM_READY!==0 timeout /t 2 /nobreak >nul
    )
)
IF !_APPIUM_READY!==0 (
    echo   WARN  Appium did not respond on port 4723.
    echo         Appium log: %APPIUM_LOG%
    echo [5/5] WARN: Appium not ready on 4723 >> "%LOG%"
) ELSE (
    echo   Appium ready on port 4723.
    echo [5/5] Appium ready >> "%LOG%"
)

start "" /B powershell -NoProfile -Command ^
  "$u='http://localhost:5003';for($i=0;$i-lt 30;$i++){try{if((Invoke-WebRequest $u -TimeoutSec 1 -UseBasicParsing).StatusCode -eq 200){start $u;break}}catch{};Start-Sleep 1}"

echo.
echo   Starting web server at http://localhost:5003
echo   (Close this window or run STOP.bat to stop)
echo.
echo [5/5] web server start (log: %WEB_LOG%) >> "%LOG%"
SET "AK_NO_BROWSER=1"
"%PY%" "%A%\web\app.py" >> "%WEB_LOG%" 2>&1
SET "_WS_EXIT=!ERRORLEVEL!"
IF "!_WS_EXIT!"=="" SET "_WS_EXIT=unknown"
echo [5/5] web server exit: !_WS_EXIT! >> "%LOG%"
echo.
IF "!_WS_EXIT!"=="0" (
    echo   Web server stopped normally.
    echo [5/5] web server stopped normally >> "%LOG%"
) ELSE (
    echo   ERROR  Web server exited unexpectedly.
    echo          Exit Code: !_WS_EXIT!
    echo          Web log:  %WEB_LOG%
    echo          Main log: %LOG%
    echo [5/5] FAIL: web server exit !_WS_EXIT! >> "%LOG%"
)
echo.
echo   Press any key to close...
pause >nul
"""


def _download(url: str, label: str) -> bytes:
    print(f"  Downloading {label}...", end=" ", flush=True)
    with urllib.request.urlopen(url, timeout=180) as r:
        data = r.read()
    print(f"done ({len(data)//1024//1024}MB)")
    return data


def _setup_python(tmp: Path) -> Path:
    data = _download(PYTHON_URL, f"Python {PYTHON_VERSION} embeddable")
    python_dir = tmp / "python"
    python_dir.mkdir()

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(python_dir)

    # Enable site-packages in the ._pth file
    for pth in python_dir.glob("python*._pth"):
        content = pth.read_text(encoding="utf-8")
        content = content.replace("#import site", "import site")
        if "Lib\\site-packages" not in content:
            content += "\nLib\\site-packages\n"
        pth.write_text(content, encoding="utf-8")

    # Install runtime packages (Windows-compatible wheels, cross-platform)
    site_pkg = python_dir / "Lib" / "site-packages"
    site_pkg.mkdir(parents=True, exist_ok=True)

    # Build runtime requirements — keep the same version pins as
    # requirements.txt (issue #25: stripping them meant Windows testers got
    # whatever was latest at build time, different from Mac's pinned
    # install and not reproducible build-to-build for the same release).
    reqs = ROOT / "requirements.txt"
    runtime_lines = []
    for ln in reqs.read_text().splitlines():
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(skip in stripped for skip in SKIP_PACKAGES):
            continue
        runtime_lines.append(stripped)
    tmp_req = tmp / "requirements_runtime.txt"
    tmp_req.write_text("\n".join(runtime_lines))

    print("  Installing Python packages...", end=" ", flush=True)
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "--target", str(site_pkg),
        "-r", str(tmp_req),
        "--quiet",
    ], check=True)
    print("done")
    return python_dir


def _setup_node(tmp: Path) -> Path:
    data = _download(NODE_URL, f"Node.js {NODE_VERSION}")
    node_dir = tmp / "node"

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            rel = "/".join(member.split("/")[1:])
            if not rel:
                continue
            target = node_dir / Path(rel)
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(member))
    return node_dir


def _bundle_adb(tmp: Path) -> None:
    data = _download(ADB_URL, "adb (platform-tools)")
    pt_dir = tmp / "runtime" / "platform-tools"
    pt_dir.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name in ADB_FILES:
                (pt_dir / Path(name).name).write_bytes(z.read(name))


def _add_dir(zf: zipfile.ZipFile, src: Path, arc_prefix: str):
    SKIP = {"__pycache__", ".pyc", ".DS_Store", ".git"}
    for f in src.rglob("*"):
        if f.is_file() and not any(s in str(f) for s in SKIP):
            zf.write(f, arc_prefix + "/" + f.relative_to(src).as_posix())


def _add_config(zf: zipfile.ZipFile, arc_prefix: str):
    EXCLUDE = {"_web_run.yaml", "_web_reg.yaml"}
    config_dir = ROOT / "config"
    if not config_dir.exists():
        return
    for f in sorted(config_dir.iterdir()):
        if f.is_file() and f.name not in EXCLUDE:
            zf.write(f, f"{arc_prefix}/{f.name}")


def _validate_run_bat():
    errors = []
    if "Add-Content" in RUN_BAT:
        errors.append("Add-Content found in RUN_BAT (causes log file lock conflict)")
    if "_APPIUM_CMD_BIN" not in RUN_BAT:
        errors.append("_APPIUM_CMD_BIN candidate path not found in RUN_BAT")
    if "_APPIUM_CMD_NM" not in RUN_BAT:
        errors.append("_APPIUM_CMD_NM candidate path not found in RUN_BAT")
    if "java_verify" not in RUN_BAT:
        errors.append(":java_verify label not found in RUN_BAT")
    if "-> Entering" not in RUN_BAT:
        errors.append("Step transition log markers not found in RUN_BAT")
    if errors:
        for e in errors:
            print(f"  BUILD ASSERTION FAILED: {e}")
        raise SystemExit("Aborting build: RUN_BAT validation failed.")


def build(out_dir: Path):
    _validate_run_bat()

    name = f"AccurKardia-Windows-Standalone-v{VERSION}-{TODAY}.zip"
    path = out_dir / name

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        print(f"\nBuilding standalone bundle → {path}\n")

        python_dir = _setup_python(tmp)
        node_dir   = _setup_node(tmp)
        _bundle_adb(tmp)

        print(f"  Packaging zip...", end=" ", flush=True)
        R = f"AccurKardia-Windows-Standalone-v{VERSION}"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Root launchers
            zf.writestr(f"{R}/run.bat", RUN_BAT.replace("\n", "\r\n"))
            zf.write(ROOT / "STOP.bat", f"{R}/STOP.bat")
            if (ROOT / "smoke.bat").exists():
                zf.write(ROOT / "smoke.bat", f"{R}/smoke.bat")
            for fname in ["README_WINDOWS_KR.txt", "README_WINDOWS_EN.txt"]:
                if (ROOT / fname).exists():
                    zf.write(ROOT / fname, f"{R}/{fname}")

            P = f"{R}/automation"
            # Bundled runtimes
            _add_dir(zf, python_dir,        f"{P}/python")
            _add_dir(zf, node_dir,          f"{P}/node")
            _add_dir(zf, tmp / "runtime",   f"{P}/runtime")

            # App code
            zf.write(ROOT / "requirements.txt", f"{P}/requirements.txt")
            _add_dir(zf, ROOT / "src",      f"{P}/src")
            _add_dir(zf, ROOT / "web",      f"{P}/web")
            _add_dir(zf, ROOT / "scripts",  f"{P}/scripts")
            _add_config(zf,                  f"{P}/config")

        size_mb = path.stat().st_size // 1024 // 1024
        print(f"done\n\nStandalone ZIP: {path}  ({size_mb} MB)")


def main():
    ap = argparse.ArgumentParser(description="Build AccurKardia Windows Standalone ZIP")
    ap.add_argument("--out", default=str(Path.home() / "Desktop"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build(out)
    print("\nDone.")

if __name__ == "__main__":
    main()
