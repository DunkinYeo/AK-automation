@echo off
REM =============================================================
REM  AccurKardia -- Installation Smoke Check
REM  Double-click AFTER extracting the ZIP, BEFORE your first run.
REM  Takes ~30s, needs NO phone. Share a screenshot of the result.
REM =============================================================
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "A=%~dp0automation"

if not exist "%A%\python\python.exe" (
    echo FAIL: automation\python\python.exe not found.
    echo Did you fully extract the ZIP? Right-click the ZIP ^> Extract All,
    echo then run smoke.bat from the extracted folder.
    echo.
    pause
    exit /b 1
)

"%A%\python\python.exe" "%A%\scripts\smoke_test.py"
echo.
echo (Screenshot this window and share it if anything failed.)
pause
