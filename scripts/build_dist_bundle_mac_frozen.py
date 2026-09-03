"""
Frozen-executable variant of build_dist_bundle_mac.py (issue #46 --
source-protection). Same Node.js + ADB bundling and Appium/UiAutomator2/
XCUITest/WDA bootstrap as the raw-source version, but the Python
application itself is compiled into a single executable via PyInstaller
(scripts/pyinstaller_build.py) instead of shipping loose src/*.py,
web/*.py files that anyone can open and read.

Deliberately kept SEPARATE from build_dist_bundle_mac.py -- that script
is the one actually wired into release.yml and already shipping v1.1.4;
this one is new capability, not yet swapped in as the default, pending
real-device validation (Android + iOS both, unlike the MA sibling
project which only needed Android).

Creates:
  AccurKardia-Mac-Standalone-Frozen-v{VERSION}-{TODAY}.zip

Usage:
  python scripts/build_dist_bundle_mac_frozen.py
  python scripts/build_dist_bundle_mac_frozen.py --out ~/Desktop
"""

import argparse
import datetime
import io
import platform
import stat
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from pyinstaller_build import freeze  # noqa: E402

TODAY = datetime.date.today().strftime("%Y%m%d")
VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "0.0.0"

NODE_VERSION = "22.13.1"
ARCH = platform.machine()  # "arm64" (Apple Silicon) or "x86_64" (Intel)
NODE_ARCH = "arm64" if ARCH == "arm64" else "x64"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-darwin-{NODE_ARCH}.tar.gz"

ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"

# Unlike build_dist_bundle_mac.py's RUN_COMMAND: no venv creation / pip
# install step at all -- Flask/Appium-Python-Client/Selenium/
# pymobiledevice3/etc. are already compiled into the frozen AKApp
# executable. Only Appium/Node/ADB/XCUITest (separate Node.js tools, not
# Python) still need their own first-run install, unchanged from the
# raw-source version. Every `"$PYTHON" -m pymobiledevice3 ...` call
# becomes `"$A/AKApp" --pymobiledevice3 ...` (see src/app_root.py's
# pymobiledevice3_argv() for the same substitution on the Python side) --
# including the one Python one-liner (`python -c "..."` to parse the
# usbmux JSON output), which can't be reproduced with a frozen binary at
# all (no general -c/eval mode -- deliberately not added, since that
# would turn the dispatcher into an arbitrary-code-eval surface just for
# this one convenience). Replaced with a grep/cut extraction of the first
# UniqueDeviceID instead -- pragmatic, since the JSON shape here is fixed
# and produced by our own trusted pymobiledevice3 call, not user input.
RUN_COMMAND = """\
#!/bin/bash
# AccurKardia -- Launch Test Environment (Mac Standalone, Frozen)
# Double-click this file in Finder to start.

chmod +x "$0" 2>/dev/null || true
cd "$(dirname "$0")" || { echo "ERROR: cd failed."; read -r _; exit 1; }

A="$PWD/automation"
NODE="$A/node/bin"
ADB="$A/runtime/platform-tools"
APPIUM_INSTALL="$A/appium"
APPIUM_CMD="$APPIUM_INSTALL/bin/appium"
export APPIUM_HOME="$A/appium_home"
export ANDROID_HOME="$A/runtime"
export ANDROID_SDK_ROOT="$A/runtime"
mkdir -p "$APPIUM_HOME"
LOG="/tmp/ak_run_$(date +%Y%m%d_%H%M%S).log"

export PATH="$NODE:$ADB:$PATH"
export PYTHONUNBUFFERED=1

echo ""
echo "  =============================================="
echo "  |  AccurKardia -- Starting (Standalone)     |"
echo "  =============================================="
echo ""

# ── Remove Gatekeeper quarantine from bundled binaries ───────────────────────
xattr -rd com.apple.quarantine "$A" 2>/dev/null || true
chmod +x "$ADB/adb" "$NODE/node" "$NODE/npm" "$NODE/npx" "$A/AKApp" 2>/dev/null || true

# ── Java detection ─────────────────────────────────────────────────────────────
if [ -z "$JAVA_HOME" ]; then
    _java=$(/usr/libexec/java_home 2>/dev/null)
    [ -n "$_java" ] && [ -d "$_java" ] && export JAVA_HOME="$_java"
fi
if [ -z "$JAVA_HOME" ]; then
    for _p in /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
              /Library/Java/JavaVirtualMachines/*/Contents/Home; do
        [ -d "$_p" ] && export JAVA_HOME="$_p" && break
    done
fi
if [ -n "$JAVA_HOME" ]; then
    export PATH="$JAVA_HOME/bin:$PATH"
else
    echo "  Java not found. Installing via Homebrew (one-time only)..."
    if ! command -v brew >/dev/null 2>&1; then
        NONINTERACTIVE=1 /bin/bash -c \
            "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
            >> "$LOG" 2>&1
        for _b in "/opt/homebrew/bin/brew" "/usr/local/bin/brew"; do
            [ -f "$_b" ] && eval "$("$_b" shellenv)" 2>/dev/null && break
        done
    fi
    brew install openjdk --quiet >> "$LOG" 2>&1
    _java=$(/usr/libexec/java_home 2>/dev/null)
    if [ -z "$_java" ]; then
        for _p in \
            "$(brew --prefix openjdk 2>/dev/null)/libexec/openjdk.jdk/Contents/Home" \
            "/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"; do
            [ -d "$_p" ] && _java="$_p" && break
        done
    fi
    if [ -n "$_java" ] && [ -d "$_java" ]; then
        export JAVA_HOME="$_java"
        export PATH="$JAVA_HOME/bin:$PATH"
        echo "  OK  Java installed."
    else
        echo "  WARN  Java install failed. Install manually: brew install openjdk"
    fi
    echo ""
fi

# ── First run: install Appium ─────────────────────────────────────────────
# Pinned versions (appium@3.5.2, uiautomator2@4.1.5, xcuitest@11.17.1) --
# see build_dist_bundle_mac.py's RUN_COMMAND for the incident this guards against.
if [ ! -f "$APPIUM_CMD" ]; then
    echo "  First run: installing Appium (~2 min, one-time only)..."
    "$NODE/npm" install -g appium@3.5.2 --prefix "$APPIUM_INSTALL" --quiet --no-progress 2>>"$LOG"
    if [ $? -ne 0 ]; then
        echo "  FAIL  Appium installation failed. Check internet connection."
        read -r -p "  Press Enter to close... " _
        exit 1
    fi
    echo "  OK  Appium installed."
    echo ""
fi

"$ADB/adb" shell settings put global verifier_verify_adb_installs 0 >> "$LOG" 2>&1 || true
"$ADB/adb" shell settings put global package_verifier_enable 0 >> "$LOG" 2>&1 || true

# ── First run: install UiAutomator2 driver ────────────────────────────────
if ! "$APPIUM_CMD" driver list --installed 2>/dev/null | grep -qi "uiautomator2"; then
    echo "  Installing UiAutomator2 driver (one-time only)..."
    "$APPIUM_CMD" driver install uiautomator2@4.1.5 2>&1 | tee -a "$LOG"
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        echo "  FAIL  UiAutomator2 driver installation failed."
        echo "  Log: $LOG"
        read -r -p "  Press Enter to close... " _
        exit 1
    fi
    echo "  OK  UiAutomator2 driver installed."
    echo ""
fi

# ── iOS support (optional, non-blocking) ──────────────────────────────────
if ! "$APPIUM_CMD" driver list --installed 2>/dev/null | grep -qi "xcuitest"; then
    echo "  Installing XCUITest driver for iOS (one-time only)..."
    "$APPIUM_CMD" driver install xcuitest@11.17.1 >> "$LOG" 2>&1 \
        && echo "  OK  XCUITest driver installed." \
        || echo "  WARN  XCUITest driver install failed (iOS unavailable). Log: $LOG"
    echo ""
fi

IOS_UDID=$("$A/AKApp" --pymobiledevice3 usbmux list 2>/dev/null \
    | grep -o '"UniqueDeviceID"[^,}]*' | head -1 | grep -o '"[^"]*"$' | tr -d '"')
if [ -n "$IOS_UDID" ]; then
    echo "  iPhone detected: $IOS_UDID"
    if [ -f "$A/runtime/WDA.ipa" ]; then
        if ! "$A/AKApp" --pymobiledevice3 apps list 2>/dev/null | grep -q "WebDriverAgentRunner"; then
            echo "  Installing WebDriverAgent on device (one-time only)..."
            if "$A/AKApp" --pymobiledevice3 apps install "$A/runtime/WDA.ipa" >> "$LOG" 2>&1; then
                echo "  OK  WebDriverAgent installed."
            else
                echo "  WARN  WDA install failed — this iPhone may not be registered."
                echo "        Send this UDID to the automation admin: $IOS_UDID"
            fi
        fi
        # Developer Mode (iOS 16+, needs one reboot; ignore errors if already on)
        "$A/AKApp" --pymobiledevice3 amfi enable-developer-mode >> "$LOG" 2>&1 || true
    else
        echo "  NOTE  runtime/WDA.ipa not bundled — iOS testing unavailable in this zip."
    fi
    echo ""
fi

# ── Start Appium ───────────────────────────────────────────────────────────
echo "  Starting Appium..."
nohup "$APPIUM_CMD" --relaxed-security >> "$LOG" 2>&1 &
APPIUM_PID=$!
sleep 2

# ── Open browser when server is ready ─────────────────────────────────────
(
    for i in $(seq 1 30); do
        if curl -sf --max-time 1 http://localhost:5003 >/dev/null 2>&1; then
            open "http://localhost:5003"
            exit 0
        fi
        sleep 1
    done
) &

# ── Sleep prevention ────────────────────────────────────────────────────────
if command -v caffeinate >/dev/null 2>&1; then
    caffeinate -dims &
    CAFF_PID=$!
fi

echo "  Starting web server at http://localhost:5003"
echo "  (First launch may take up to ~30s the very first time -- macOS"
echo "   scans a newly-installed program before it's allowed to run.)"
echo "  (Close this window or run STOP.command to stop)"
echo ""

export AK_NO_BROWSER=1
"$A/AKApp" --web

# ── Cleanup ─────────────────────────────────────────────────────────────────
kill "$APPIUM_PID" 2>/dev/null || true
[ -n "$CAFF_PID" ] && kill "$CAFF_PID" 2>/dev/null || true
echo ""
echo "  Web server stopped."
read -r -p "  Press Enter to close... " _
"""

STOP_COMMAND = """\
#!/bin/bash
# AccurKardia -- Stop all services (Frozen build)
pkill -f "AKApp --web" 2>/dev/null && echo "  Web server stopped." || echo "  Web server was not running."
pkill -f "appium" 2>/dev/null && echo "  Appium stopped." || echo "  Appium was not running."
pkill -f "caffeinate" 2>/dev/null
echo ""
echo "  Done."
read -r -p "  Press Enter to close... " _
"""

SMOKE_COMMAND = """\
#!/bin/bash
# =============================================================
#  AccurKardia -- Installation Smoke Check (Mac, Frozen build)
#  Double-click AFTER extracting the ZIP, BEFORE your first run.
#  No Python setup step -- the app is a single compiled executable.
#  Share a screenshot of the result if anything failed.
# =============================================================
chmod +x "$0" 2>/dev/null || true
cd "$(dirname "$0")" || { echo "ERROR: cd failed."; read -r _; exit 1; }
A="$PWD/automation"
export PATH="$A/node/bin:$A/runtime/platform-tools:$PATH"
export PYTHONUNBUFFERED=1

if [ ! -d "$A" ]; then
    echo "  FAIL: automation/ folder not found."
    echo "  Did you fully extract the ZIP? Extract it first, then run"
    echo "  smoke.command from the extracted folder."
    read -r -p "  Press Enter to close... " _
    exit 1
fi

xattr -rd com.apple.quarantine "$A" 2>/dev/null || true
chmod +x "$A/AKApp" 2>/dev/null || true

echo "  (First launch may take up to ~30s -- macOS scans a newly-"
echo "   installed program before it's allowed to run.)"
"$A/AKApp" --smoke-test
echo ""
echo "  (Screenshot this window and share it if anything failed.)"
read -r -p "  Press Enter to close... " _
"""


def _download(url: str, label: str) -> bytes:
    print(f"  Downloading {label}...", end=" ", flush=True)
    with urllib.request.urlopen(url, timeout=180) as r:
        data = r.read()
    print(f"done ({len(data) // 1024 // 1024}MB)")
    return data


def _setup_node(tmp: Path) -> Path:
    data = _download(NODE_URL, f"Node.js {NODE_VERSION} macOS-{NODE_ARCH}")
    node_dir = tmp / "node"
    node_dir.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for member in tf.getmembers():
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            member.name = parts[1]
            tf.extract(member, node_dir)

    for script, target in [("npm", "npm-cli.js"), ("npx", "npx-cli.js")]:
        wrapper = node_dir / "bin" / script
        if wrapper.exists() or wrapper.is_symlink():
            wrapper.unlink()
        wrapper.write_text(
            f'#!/usr/bin/env node\nrequire("../lib/node_modules/npm/bin/{target}")\n'
        )
        wrapper.chmod(0o755)

    return node_dir


def _bundle_adb(tmp: Path) -> None:
    data = _download(ADB_URL, "ADB platform-tools (macOS)")
    pt_dir = tmp / "runtime" / "platform-tools"
    pt_dir.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.startswith("platform-tools/") and not name.endswith("/"):
                fname = name.split("/", 1)[1]
                if fname:
                    out = pt_dir / fname
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(z.read(name))
                    out.chmod(0o755)


def _add_dir(zf: zipfile.ZipFile, src: Path, arc_prefix: str):
    SKIP = {"__pycache__", ".pyc", ".DS_Store", ".git", ".venv"}
    for f in src.rglob("*"):
        if f.is_file() and not any(s in str(f) for s in SKIP):
            arc_path = arc_prefix + "/" + f.relative_to(src).as_posix()
            file_stat = f.stat()
            mtime = time.localtime(file_stat.st_mtime)
            info = zipfile.ZipInfo(arc_path, date_time=mtime[:6])
            unix_perm = stat.S_IMODE(file_stat.st_mode)
            info.external_attr = (unix_perm << 16) | 0x8000_0000
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, f.read_bytes())


def _add_script(zf: zipfile.ZipFile, arc_name: str, content: str):
    info = zipfile.ZipInfo(arc_name, date_time=time.localtime()[:6])
    info.external_attr = (0o755 << 16) | 0x8000_0000
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, content)


def _add_config(zf: zipfile.ZipFile, arc_prefix: str):
    EXCLUDE = {"_web_run.yaml", "_web_reg.yaml"}
    config_dir = ROOT / "config"
    if not config_dir.exists():
        return
    for f in sorted(config_dir.iterdir()):
        if f.is_file() and f.name not in EXCLUDE:
            zf.write(f, f"{arc_prefix}/{f.name}")


def build(out_dir: Path) -> Path:
    name = f"AccurKardia-Mac-Standalone-Frozen-v{VERSION}-{TODAY}.zip"
    path = out_dir / name

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        print(f"\nBuilding Mac standalone (frozen) bundle -> {path}\n")

        node_dir = _setup_node(tmp)
        _bundle_adb(tmp)

        print("  Freezing Python application with PyInstaller...", end=" ", flush=True)
        frozen_dir = freeze(
            dist_dir=tmp / "pyinstaller_dist",
            work_dir=tmp / "pyinstaller_work",
            spec_dir=tmp / "pyinstaller_spec",
        )
        print("done")

        print("  Packaging zip...", end=" ", flush=True)
        R = f"AccurKardia-Mac-Standalone-Frozen-v{VERSION}"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            _add_script(zf, f"{R}/run.command", RUN_COMMAND)
            _add_script(zf, f"{R}/STOP.command", STOP_COMMAND)
            _add_script(zf, f"{R}/smoke.command", SMOKE_COMMAND)
            for fname in ["README_MAC_KR.txt", "README_MAC_EN.txt"]:
                if (ROOT / fname).exists():
                    zf.write(ROOT / fname, f"{R}/{fname}")

            P = f"{R}/automation"
            _add_dir(zf, node_dir,        f"{P}/node")
            _add_dir(zf, tmp / "runtime", f"{P}/runtime")
            _add_dir(zf, frozen_dir,      P)
            _add_config(zf,               f"{P}/config")
            # web/templates/ stays loose (not PyInstaller --add-data'd --
            # see pyinstaller_build.py's docstring). Flask's
            # template_folder=str(ROOT/"web"/"templates") expects it here.
            _add_dir(zf, ROOT / "web" / "templates", f"{P}/web/templates")

            wda_ipa = ROOT / "runtime" / "WDA.ipa"
            if wda_ipa.exists():
                zf.write(wda_ipa, f"{P}/runtime/WDA.ipa")
                print("(+ WDA.ipa bundled)", end=" ", flush=True)

        size_mb = path.stat().st_size // 1024 // 1024
        print(f"done\n\nMac Standalone (Frozen) ZIP: {path}  ({size_mb} MB)")
    return path


def main():
    ap = argparse.ArgumentParser(description="Build AccurKardia Mac Standalone ZIP (frozen executable)")
    ap.add_argument("--out", default=str(Path.home() / "Desktop"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build(out)
    print("\nDone.")


if __name__ == "__main__":
    main()
