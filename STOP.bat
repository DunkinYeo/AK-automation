@echo off
setlocal
cd /d "%~dp0"
REM AccurKardia -- Stop All Services

echo.
echo   +==============================================+
echo   ^|  AccurKardia -- Stopping All Services...  ^|
echo   +==============================================+
echo.

REM -- Stop web server (port 5002) -----------------------------
echo   Stopping web server (port 5002)...
SET _STOPPED_WEB=0
FOR /F "tokens=5" %%P IN ('netstat -ano 2^>nul ^| findstr ":5002 " ^| findstr "LISTENING"') DO (
    IF NOT "%%P"=="0" (
        taskkill /PID %%P /F >nul 2>&1
        SET _STOPPED_WEB=1
    )
)
IF "%_STOPPED_WEB%"=="1" (
    echo   OK  Web server stopped.
) ELSE (
    echo   Web server was not running on port 5002.
)

REM -- Stop Appium (port 4723) ---------------------------------
echo   Stopping Appium server (port 4723)...
SET _STOPPED_APPIUM=0
FOR /F "tokens=5" %%P IN ('netstat -ano 2^>nul ^| findstr ":4723 " ^| findstr "LISTENING"') DO (
    IF NOT "%%P"=="0" (
        taskkill /PID %%P /F >nul 2>&1
        SET _STOPPED_APPIUM=1
    )
)
IF "%_STOPPED_APPIUM%"=="1" (
    echo   OK  Appium server stopped.
) ELSE (
    echo   Appium server was not running.
)

REM -- Stop test runner (main.py) ------------------------------
echo   Stopping test runner...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and ($_.CommandLine -like '*main.py*' -or $_.CommandLine -like '*app.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" ^
  >nul 2>&1
echo   OK  Test runner stopped.

echo.
echo   +==============================================+
echo   ^|   All services stopped. Safe to close.    ^|
echo   +==============================================+
echo.
pause >nul
EXIT /B 0
