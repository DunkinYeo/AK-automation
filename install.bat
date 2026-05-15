@echo off
setlocal
cd /d "%~dp0"

SET "LOG=%TEMP%\ak_install.log"
SET FAILED=0
SET "PYTHON_EXE=python"
SET "PATH=%ProgramFiles%\nodejs;%APPDATA%\npm;%PATH%"

echo AccurKardia install started > "%LOG%"

echo.
echo   AccurKardia -- Windows Setup
echo.
echo   Log: %LOG%
echo.

REM ============================================================
REM [1/6] Python
REM ============================================================
echo [1/6] Python...
python --version >nul 2>&1
IF NOT ERRORLEVEL 1 (
    echo   PASS  Python
    echo [1/6] PASS >> "%LOG%"
    SET "PYTHON_EXE=python"
    GOTO :step2
)
py -3 --version >nul 2>&1
IF NOT ERRORLEVEL 1 (
    echo   PASS  Python (via py.exe)
    SET "_PY3EXE="
    FOR /F "usebackq tokens=*" %%P IN (`py -3 -c "import sys; print(sys.executable)"`) DO SET "_PY3EXE=%%P"
    IF DEFINED _PY3EXE (SET "PYTHON_EXE=%_PY3EXE%") ELSE (SET "PYTHON_EXE=py")
    SET "_PY3EXE="
    GOTO :step2
)
REM Search common install paths (Python installed without Add-to-PATH)
SET "_PY_PATH="
FOR /F "usebackq tokens=*" %%P IN (`powershell -NoProfile -Command "$f=$null;foreach($v in '313','312','311','310'){foreach($b in ([Environment]::GetFolderPath('LocalApplicationData')+'\Programs\Python\Python'+$v,$env:PROGRAMFILES+'\Python'+$v,$env:PROGRAMFILES+'\Python\Python'+$v)){$e=$b+'\python.exe';if(Test-Path $e){$f=$e;break}};if($f){break}};if($f){$f}" 2^>nul`) DO SET "_PY_PATH=%%P"
IF DEFINED _PY_PATH (
    SET "PYTHON_EXE=%_PY_PATH%"
    FOR %%D IN ("%_PY_PATH%") DO SET "PATH=%%~dpD;%%~dpDScripts;%PATH%"
    SET "_PY_PATH="
    echo   PASS  Python found at %PYTHON_EXE%
    echo [1/6] PASS (common path) >> "%LOG%"
    GOTO :step2
)
echo   Python not found. Installing via winget...
winget --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo   FAIL  winget not available.
    echo   Download Python 3.10+ from https://www.python.org/downloads/
    pause
    SET FAILED=1
    GOTO :step2
)
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
IF ERRORLEVEL 1 (
    echo   WARN  winget install failed.
    echo   Download Python 3.10+ from https://www.python.org/downloads/
    pause
    SET FAILED=1
    GOTO :step2
)
SET "_PYDIR="
FOR /F "usebackq tokens=*" %%P IN (`powershell -NoProfile -Command "try { Get-ChildItem ([System.Environment]::GetFolderPath('LocalApplicationData') + '\Programs\Python') -Filter 'Python3*' -ErrorAction Stop | Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName } catch { '' }" 2^>nul`) DO SET "_PYDIR=%%P"
IF NOT DEFINED _PYDIR (
    FOR /F "usebackq tokens=*" %%P IN (`powershell -NoProfile -Command "try { Split-Path -Parent (Get-Command python).Source } catch { '' }" 2^>nul`) DO SET "_PYDIR=%%P"
)
IF DEFINED _PYDIR (
    SET "PATH=%_PYDIR%;%_PYDIR%\Scripts;%PATH%"
)
python --version >nul 2>&1
IF NOT ERRORLEVEL 1 (
    SET "PYTHON_EXE=python"
    echo   PASS  Python installed.
    GOTO :step2
)
echo   FAIL  Python not responding. Re-run install.bat in a new Command Prompt.
pause
SET FAILED=1

REM ============================================================
REM [2/6] Node.js / npm
REM ============================================================
:step2
echo.
echo [2/6] Node.js / npm...
node --version >nul 2>&1
IF ERRORLEVEL 1 GOTO :install_node
call npm --version >nul 2>&1
IF ERRORLEVEL 1 GOTO :install_node
echo   PASS  Node.js
echo [2/6] PASS >> "%LOG%"
GOTO :step3

:install_node
echo   Node.js not found. Installing via winget...
winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
IF ERRORLEVEL 1 (
    echo   FAIL  Download Node.js LTS from https://nodejs.org/
    pause
    SET FAILED=1
    GOTO :step3
)
SET "PATH=%ProgramFiles%\nodejs;%APPDATA%\npm;%PATH%"
node --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo   FAIL  Node.js not in PATH. Re-run in a new Command Prompt.
    pause
    SET FAILED=1
    GOTO :step3
)
echo   PASS  Node.js installed.
echo [2/6] PASS >> "%LOG%"

REM ============================================================
REM [3/6] ADB
REM ============================================================
:step3
echo.
echo [3/6] ADB...
IF EXIST "runtime\platform-tools\adb.exe" (
    SET "PATH=%CD%\runtime\platform-tools;%PATH%"
)
adb version >nul 2>&1
IF NOT ERRORLEVEL 1 (
    echo   PASS  ADB ready
    echo [3/6] PASS >> "%LOG%"
    GOTO :step4
)
echo   ADB not found. Downloading Android platform-tools...
IF NOT EXIST "runtime" mkdir runtime
SET "_PTZIP=%TEMP%\ak_pt.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile '%_PTZIP%' -UseBasicParsing"
IF ERRORLEVEL 1 (
    echo   FAIL  Download failed. Check internet connection.
    pause
    SET FAILED=1
    GOTO :step4
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%_PTZIP%' -DestinationPath 'runtime' -Force"
del "%_PTZIP%" >nul 2>&1
IF NOT EXIST "runtime\platform-tools\adb.exe" (
    echo   FAIL  adb.exe not found after extraction.
    pause
    SET FAILED=1
    GOTO :step4
)
SET "PATH=%CD%\runtime\platform-tools;%PATH%"
echo   PASS  ADB installed to runtime\platform-tools
echo [3/6] PASS >> "%LOG%"

REM ============================================================
REM [4/6] Appium
REM ============================================================
:step4
echo.
echo [4/6] Appium...
SET "_APV_TMP=%TEMP%\ak_apv.txt"
call appium -v > "%_APV_TMP%" 2>&1
IF ERRORLEVEL 1 GOTO :install_appium
SET "_AV="
FOR /F "usebackq tokens=*" %%v IN ("%_APV_TMP%") DO IF NOT DEFINED _AV SET "_AV=%%v"
del "%_APV_TMP%" >nul 2>&1
echo   PASS  Appium %_AV%
echo [4/6] PASS >> "%LOG%"
GOTO :step5

:install_appium
del "%_APV_TMP%" >nul 2>&1
echo   Installing Appium via npm...
call npm install -g appium
IF ERRORLEVEL 1 (
    echo   FAIL  Try running as Administrator.
    pause
    SET FAILED=1
    GOTO :step5
)
echo   PASS  Appium installed.
echo [4/6] PASS >> "%LOG%"

REM ============================================================
REM [5/6] UiAutomator2 driver
REM ============================================================
:step5
echo.
echo [5/6] UiAutomator2 driver...
SET "_DRV_TMP=%TEMP%\ak_drv.txt"
call appium driver list --installed > "%_DRV_TMP%" 2>&1
findstr /i "uiautomator2" "%_DRV_TMP%" >nul 2>&1
IF ERRORLEVEL 1 GOTO :install_uia2
echo   PASS  UiAutomator2 driver already installed.
echo [5/6] PASS >> "%LOG%"
del "%_DRV_TMP%" >nul 2>&1
GOTO :step6

:install_uia2
del "%_DRV_TMP%" >nul 2>&1
echo   Installing UiAutomator2 driver...
call appium driver install uiautomator2
IF ERRORLEVEL 1 (
    echo   FAIL  Try: appium driver install uiautomator2
    pause
    SET FAILED=1
    GOTO :step6
)
echo   PASS  UiAutomator2 driver installed.
echo [5/6] PASS >> "%LOG%"

REM ============================================================
REM [6/6] Python packages
REM ============================================================
:step6
echo.
echo [6/6] Python packages...
IF NOT EXIST ".venv" (
    echo   Creating virtual environment...
    "%PYTHON_EXE%" -m venv .venv
    IF ERRORLEVEL 1 (
        echo   FAIL  Could not create .venv.
        pause
        SET FAILED=1
        GOTO :summary
    )
)
echo   Installing packages from requirements.txt...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt
IF ERRORLEVEL 1 (
    echo   FAIL  pip install failed. Check your network connection.
    pause
    SET FAILED=1
    GOTO :summary
)
echo   PASS  Packages installed.
echo [6/6] PASS >> "%LOG%"
IF NOT EXIST "logs"    mkdir logs
IF NOT EXIST "runtime" mkdir runtime

:summary
echo.
IF "%FAILED%"=="1" (
    echo   Setup encountered errors. Review the messages above.
    echo   Full log: %LOG%
    echo.
    pause
    EXIT /B 1
)
echo   ========================
echo   Setup complete.
echo   Run run.bat to start.
echo   ========================
echo.
echo   Full log: %LOG%
echo.
pause
EXIT /B 0
