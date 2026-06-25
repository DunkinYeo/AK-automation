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

SKIP_PACKAGES = {"black", "ruff", "pre-commit"}  # dev-only, not needed at runtime

RUN_BAT = r"""@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

SET "A=%CD%\automation"
SET "PY=%A%\python\python.exe"
SET "NODE=%A%\node"
SET "ADB=%A%\runtime\platform-tools"
SET "APPIUM_INSTALL=%A%\appium"
SET "APPIUM_HOME=%A%\appium_home"
SET "_APPIUM_CMD=%APPIUM_INSTALL%\node_modules\.bin\appium.cmd"
SET "LOG=%TEMP%\ak_run.log"

SET "ANDROID_HOME=%A%\runtime"
SET "ANDROID_SDK_ROOT=%A%\runtime"
SET "PATH=%ADB%;%NODE%;%PATH%"
SET "PYTHONPATH=%A%"

IF NOT EXIST "%APPIUM_HOME%" mkdir "%APPIUM_HOME%"

echo.
echo   +==============================================+
echo   ^|   AccurKardia -- Starting (Standalone)     ^|
echo   +==============================================+
echo.

REM ── 이미 실행 중인지 확인 (포트 5003) ─────────────────────────────────────
netstat -ano 2>nul | findstr ":5003 " | findstr "LISTENING" >nul
IF NOT ERRORLEVEL 1 (
    echo   AccurKardia가 이미 실행 중입니다.
    start http://localhost:5003
    pause & EXIT /B 0
)

REM ── Unblock-File: 인터넷 다운로드 격리 해제 (관리자 권한 불필요) ──────────
powershell -NoProfile -WindowStyle Hidden -Command ^
  "Get-ChildItem '%A%' -Recurse | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

REM ── Windows Defender 예외 추가 (관리자 권한 있을 때만 동작, 없으면 무시) ──
powershell -NoProfile -WindowStyle Hidden -Command ^
  "Add-MpPreference -ExclusionPath '%A%' -ErrorAction SilentlyContinue" >nul 2>&1

REM ── Java (JDK) 감지 ────────────────────────────────────────────────────────
IF NOT "%JAVA_HOME%"=="" GOTO :java_set_path

REM 1) PATH에서 탐색 — keytool 있는 진짜 JDK만 허용 (Windows Store stub 제외)
FOR /F "tokens=*" %%J IN ('where java 2^>nul') DO (
    FOR %%P IN ("%%~dpJ..") DO (
        IF EXIST "%%~fP\bin\keytool.exe" (
            SET "JAVA_HOME=%%~fP"
            GOTO :java_set_path
        )
    )
)

REM 2) 일반 설치 경로 직접 탐색 (PATH 갱신 불필요)
FOR %%B IN (
    "%ProgramFiles%\Eclipse Adoptium"
    "%ProgramFiles%\Java"
    "%ProgramFiles%\Microsoft"
    "%ProgramFiles%\OpenJDK"
    "%ProgramFiles(x86)%\Java"
) DO (
    FOR /D %%D IN ("%%~B\jdk*") DO (
        IF EXIST "%%D\bin\keytool.exe" (
            SET "JAVA_HOME=%%D"
            GOTO :java_set_path
        )
    )
)

REM 3) Java 없음 — winget으로 자동 설치 (user scope, 관리자 불필요)
echo   Java(JDK) not found. Installing automatically via winget...
echo   (one-time, ~2 min, internet required)
winget install --id Microsoft.OpenJDK.21 --scope user --silent ^
  --accept-package-agreements --accept-source-agreements 2>>"%LOG%"
IF ERRORLEVEL 1 (
    REM user scope 실패 시 machine scope 재시도 (관리자 필요할 수 있음)
    winget install --id Microsoft.OpenJDK.21 --silent ^
      --accept-package-agreements --accept-source-agreements 2>>"%LOG%"
)

REM winget 설치 후 PATH 갱신 없이 파일 경로로 직접 탐색
FOR %%B IN (
    "%ProgramFiles%\Microsoft"
    "%ProgramFiles%\Eclipse Adoptium"
    "%LOCALAPPDATA%\Microsoft"
    "%LOCALAPPDATA%\Programs\Eclipse Adoptium"
) DO (
    FOR /D %%D IN ("%%~B\jdk*") DO (
        IF EXIST "%%D\bin\keytool.exe" (
            SET "JAVA_HOME=%%D"
            GOTO :java_set_path
        )
    )
)

echo   WARN  Java(JDK) 자동 설치 실패.
echo         수동 설치 후 재실행하세요: https://adoptium.net
echo         또는 터미널에서: winget install Microsoft.OpenJDK.21
echo.
GOTO :java_done

:java_set_path
SET "PATH=%JAVA_HOME%\bin;%PATH%"
echo   Java: %JAVA_HOME%

:java_done

REM ── Install Appium if needed (first run only) ──────────────────────────────
IF NOT EXIST "%_APPIUM_CMD%" (
    echo.
    echo   Installing Appium (first run only, ~2 min^)...
    call "%NODE%\npm.cmd" install -g appium --prefix "%APPIUM_INSTALL%" --quiet --no-progress 2>>"%LOG%"
    IF ERRORLEVEL 1 (
        echo.
        echo   FAIL  Appium 설치 실패.
        echo         인터넷 연결을 확인하고 재실행하세요.
        echo   Log: %LOG%
        pause & EXIT /B 1
    )
    echo   OK    Appium installed.
)

REM ── Install UiAutomator2 driver if needed ──────────────────────────────────
"%_APPIUM_CMD%" driver list --installed 2>nul | findstr /I "uiautomator2" >nul
IF ERRORLEVEL 1 (
    echo.
    echo   Installing UiAutomator2 driver (one-time, ~1 min^)...
    "%_APPIUM_CMD%" driver install uiautomator2 >> "%TEMP%\ak_driver.log" 2>&1
    IF ERRORLEVEL 1 (
        echo.
        echo   FAIL  UiAutomator2 driver 설치 실패.
        echo   Log: %TEMP%\ak_driver.log
        pause & EXIT /B 1
    )
    echo   OK    UiAutomator2 driver installed.
)

REM ── adb 동작 확인 (백신 격리 감지) ────────────────────────────────────────
echo.
"%ADB%\adb.exe" version >nul 2>&1
IF ERRORLEVEL 1 (
    echo   WARN  ADB를 실행할 수 없습니다.
    echo         백신 프로그램이 adb.exe를 차단했을 수 있습니다.
    echo.
    echo   해결 방법:
    echo   1. 백신 프로그램에서 아래 폴더를 예외로 추가하세요:
    echo      %A%
    echo   2. 이후 run.bat을 다시 실행하세요.
    echo.
    pause & EXIT /B 1
)

REM ── Start Appium via temp bat (nested-quote + spaces-in-path safe) ─────────
echo @echo off > "%TEMP%\ak_appium.bat"
echo "%_APPIUM_CMD%" --relaxed-security ^>^> "%LOG%" 2^>^&1 >> "%TEMP%\ak_appium.bat"
echo   Starting Appium...
start "AK - Appium" /B cmd /c "%TEMP%\ak_appium.bat"

REM Appium 준비 대기 (최대 30초)
SET _APPIUM_READY=0
FOR /L %%i IN (1,1,15) DO (
    IF !_APPIUM_READY!==0 (
        powershell -NoProfile -Command ^
          "try{if((Invoke-WebRequest 'http://localhost:4723/status' -TimeoutSec 1 -UseBasicParsing).StatusCode -eq 200){exit 0}else{exit 1}}catch{exit 1}" >nul 2>&1
        IF NOT ERRORLEVEL 1 SET _APPIUM_READY=1
        IF !_APPIUM_READY!==0 timeout /t 2 /nobreak >nul
    )
)
IF !_APPIUM_READY!==0 (
    echo   WARN  Appium이 응답하지 않습니다. Log: %LOG%
)

REM ── Open browser when server is ready ──────────────────────────────────────
start "" /B powershell -NoProfile -Command ^
  "$u='http://localhost:5003';for($i=0;$i-lt 30;$i++){try{if((Invoke-WebRequest $u -TimeoutSec 1 -UseBasicParsing).StatusCode -eq 200){start $u;break}}catch{};Start-Sleep 1}"

REM ── Start web server ────────────────────────────────────────────────────────
echo.
echo   Starting web server at http://localhost:5003
echo   (Close this window or run STOP.bat to stop)
echo.
"%PY%" "%A%\web\app.py"
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

    # Build runtime requirements without version pins for bundle compatibility
    reqs = ROOT / "requirements.txt"
    runtime_lines = []
    for ln in reqs.read_text().splitlines():
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(skip in stripped for skip in SKIP_PACKAGES):
            continue
        # Strip version pin — use latest compatible for bundle
        pkg = stripped.split("==")[0].split(">=")[0].split("<=")[0].strip()
        runtime_lines.append(pkg)
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
        top = z.namelist()[0].split("/")[0]
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


def build(out_dir: Path):
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
