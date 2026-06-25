@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
REM AccurKardia -- Launch Test Environment
REM run.bat  (project root)
REM Double-click to start Appium + Web UI.

FOR /F "usebackq tokens=*" %%T IN (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) DO SET _TS=%%T
SET "LOG=%TEMP%\ak_run_%_TS%.log"

REM ── Enable long paths (silently skipped without admin) ──────────────────────
powershell -NoProfile -WindowStyle Hidden -Command ^
  "Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled 1 -ErrorAction SilentlyContinue" >nul 2>&1
echo AccurKardia run started %DATE% %TIME% > "%LOG%"

echo.
echo   +==============================================+
echo   ^|  AccurKardia -- Launch Test Environment    ^|
echo   +==============================================+
echo.
echo   Log: %LOG%
echo.

IF NOT EXIST "web\app.py" (
    echo   ERROR: web\app.py not found.
    echo   Run run.bat from inside the AccurKardia-Automation folder.
    echo [run] FAIL: web\app.py not found >> "%LOG%"
    pause
    EXIT /B 1
)

IF NOT EXIST ".venv\Scripts\activate.bat" (
    echo   ERROR: Python environment not set up.
    echo   Please run install.bat first.
    echo [run] FAIL: .venv not found >> "%LOG%"
    pause
    EXIT /B 1
)

echo   Activating Python environment...
call .venv\Scripts\activate.bat
echo [run] .venv activated >> "%LOG%"

REM -- Android SDK detection -----------------------------------
IF EXIST "runtime\platform-tools\adb.exe" (
    SET "ANDROID_HOME=%CD%\runtime"
    SET "ANDROID_SDK_ROOT=%CD%\runtime"
    SET "PATH=%CD%\runtime\platform-tools;%PATH%"
    GOTO :sdk_ready
)
IF EXIST "runtime\android-sdk\platform-tools\adb.exe" (
    SET "ANDROID_HOME=%CD%\runtime\android-sdk"
    SET "ANDROID_SDK_ROOT=%CD%\runtime\android-sdk"
    SET "PATH=%CD%\runtime\android-sdk\platform-tools;%PATH%"
    GOTO :sdk_ready
)
IF NOT "%ANDROID_HOME%"=="" (
    IF EXIST "%ANDROID_HOME%\platform-tools\adb.exe" (
        SET "ANDROID_SDK_ROOT=%ANDROID_HOME%"
        GOTO :sdk_ready
    )
)
SET "_ADB_PATH="
FOR /F "usebackq tokens=*" %%A IN (`where adb 2^>nul`) DO IF NOT DEFINED _ADB_PATH SET "_ADB_PATH=%%A"
IF NOT "%_ADB_PATH%"=="" (
    FOR %%A IN ("%_ADB_PATH%") DO SET "_PTDIR=%%~dpA"
    SET "_PTDIR=%_PTDIR:~0,-1%"
    FOR %%A IN ("%_PTDIR%") DO SET "_SDK_ROOT=%%~dpA"
    SET "_SDK_ROOT=%_SDK_ROOT:~0,-1%"
    SET "ANDROID_HOME=%_SDK_ROOT%"
    SET "ANDROID_SDK_ROOT=%_SDK_ROOT%"
    GOTO :sdk_ready
)
echo   ERROR  Android SDK not found.
echo   Install Android Studio or run install.bat.
echo [run] FAIL: SDK not found >> "%LOG%"
pause
EXIT /B 1

:sdk_ready
SET "PATH=%ANDROID_HOME%\platform-tools;%PATH%"
SET "PATH=%ProgramFiles%\nodejs;%APPDATA%\npm;%PATH%"
echo   ANDROID_HOME=%ANDROID_HOME%
echo [run] ANDROID_HOME=%ANDROID_HOME% >> "%LOG%"

REM -- ADB device check ----------------------------------------
echo   Checking connected devices...
SET "_DEV_OK=0"
FOR /F "skip=1 tokens=1,2" %%A IN ('adb devices 2^>nul') DO (
    IF "%%B"=="device" SET "_DEV_OK=1"
)
IF "%_DEV_OK%"=="0" (
    echo.
    echo   WARN  No Android device detected.
    echo         Connect phone via USB and enable USB Debugging.
    echo         The web UI will still open.
    echo.
    echo [run] WARN: no device >> "%LOG%"
)

REM -- Appium --------------------------------------------------
echo.
echo   Checking Appium (port 4723)...
netstat -ano 2>nul | findstr ":4723 " | findstr "LISTENING" >nul 2>&1
IF ERRORLEVEL 1 GOTO :launch_appium
echo   Appium already running on port 4723.
echo [run] Appium already on 4723 >> "%LOG%"
GOTO :start_web

:launch_appium
echo   Starting Appium server...
start "AccurKardia - Appium" cmd /c "appium --relaxed-security"
echo [run] Appium started >> "%LOG%"

:start_web
echo.
echo   Starting web server on port 5003...
echo [run] Starting web server >> "%LOG%"

start "" /B powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i-lt30;$i++){try{(New-Object Net.WebClient).DownloadString('http://127.0.0.1:5003')|Out-Null;Start-Process 'http://127.0.0.1:5003';break}catch{Start-Sleep 1}}"

echo   Browser will open automatically when the server is ready.
echo   Leave this window OPEN during the test.
echo.

REM -- Sleep prevention ----------------------------------------
SET "_SLEEP_PS1=%TEMP%\ak_sleep_%_TS%.ps1"
SET "_SLEEP_PID_F=%TEMP%\ak_sleep_%_TS%.pid"
echo $PID ^| Set-Content '%_SLEEP_PID_F%' > "%_SLEEP_PS1%"
echo try { Add-Type -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);' -Name W32 -Namespace NW } catch {} >> "%_SLEEP_PS1%"
echo while ($true) { try { [NW.W32]::SetThreadExecutionState(0x80000003) ^| Out-Null } catch {}; Start-Sleep 30 } >> "%_SLEEP_PS1%"
start "" /B powershell -NoProfile -ExecutionPolicy Bypass -File "%_SLEEP_PS1%"
echo   Sleep prevention enabled.

SET "AK_NO_BROWSER=1"
IF EXIST ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe "web\app.py"
) ELSE (
    python "web\app.py"
)

echo.
echo [run] Web server exited >> "%LOG%"
taskkill /FI "WINDOWTITLE eq AccurKardia - Appium*" /F >nul 2>&1
IF EXIST "%_SLEEP_PID_F%" (
    FOR /F "usebackq" %%P IN ("%_SLEEP_PID_F%") DO taskkill /PID %%P /F >nul 2>&1
    del "%_SLEEP_PS1%" 2>nul
    del "%_SLEEP_PID_F%" 2>nul
)
echo   Web server stopped. Run STOP.bat to terminate remaining services.
echo.
pause
EXIT /B 0
