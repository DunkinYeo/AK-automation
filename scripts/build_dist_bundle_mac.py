"""
Build standalone Mac ZIP with bundled Node.js and ADB.
Python venv + packages are created on first run using system python3.
Appium is installed on first run using bundled Node.js (~1-2 min, one-time).

Creates:
  AccurKardia-Mac-Standalone-v{VERSION}-{TODAY}.zip

Usage:
  python scripts/build_dist_bundle_mac.py
  python scripts/build_dist_bundle_mac.py --out ~/Desktop
"""

import argparse
import datetime
import io
import platform
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today().strftime("%Y%m%d")
VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "0.0.0"

NODE_VERSION = "22.13.1"
ARCH = platform.machine()  # "arm64" (Apple Silicon) or "x86_64" (Intel)
NODE_ARCH = "arm64" if ARCH == "arm64" else "x64"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-darwin-{NODE_ARCH}.tar.gz"

ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"

RUN_COMMAND = """\
#!/bin/bash
# AccurKardia -- Launch Test Environment (Mac Standalone)
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
export PYTHONPATH="$A"

echo ""
echo "  =============================================="
echo "  |  AccurKardia -- Starting (Standalone)     |"
echo "  =============================================="
echo ""

# ── Remove Gatekeeper quarantine from bundled binaries ───────────────────────
xattr -rd com.apple.quarantine "$A" 2>/dev/null || true
chmod +x "$ADB/adb" "$NODE/node" "$NODE/npm" "$NODE/npx" 2>/dev/null || true

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
    # Try /usr/libexec/java_home first (brew openjdk is keg-only, may not register)
    _java=$(/usr/libexec/java_home 2>/dev/null)
    # Direct path fallback (Apple Silicon / Intel)
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

# ── Check python3 ──────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    echo "  ERROR: python3 not found."
    echo ""
    echo "  Please open Terminal and run:"
    echo "    xcode-select --install"
    echo "  Then re-open this file."
    echo ""
    read -r -p "  Press Enter to close... " _
    exit 1
fi

# ── First run: create .venv + install packages ────────────────────────────
if [ ! -f "$A/.venv/bin/python" ]; then
    echo "  First run: setting up Python environment (~1 min)..."
    python3 -m venv "$A/.venv"
    if [ $? -ne 0 ]; then
        echo "  FAIL  Python virtual environment creation failed."
        echo "        Run: xcode-select --install  then re-open this file."
        read -r -p "  Press Enter to close... " _
        exit 1
    fi
    "$A/.venv/bin/pip" install -r "$A/requirements.txt" -q
    if [ $? -ne 0 ]; then
        rm -rf "$A/.venv"
        echo "  FAIL  Python packages installation failed. Check internet connection."
        read -r -p "  Press Enter to close... " _
        exit 1
    fi
    echo "  OK  Python packages installed."
    echo ""
fi

PYTHON="$A/.venv/bin/python"

# ── First run: install Appium ─────────────────────────────────────────────
if [ ! -f "$APPIUM_CMD" ]; then
    echo "  First run: installing Appium (~2 min, one-time only)..."
    "$NODE/npm" install -g appium --prefix "$APPIUM_INSTALL" --quiet --no-progress 2>>"$LOG"
    if [ $? -ne 0 ]; then
        echo "  FAIL  Appium installation failed. Check internet connection."
        read -r -p "  Press Enter to close... " _
        exit 1
    fi
    echo "  OK  Appium installed."
    echo ""
fi

# ── First run: install UiAutomator2 driver ────────────────────────────────
# APPIUM_HOME is exported to automation/appium_home — isolated from ~/.appium
if ! "$APPIUM_CMD" driver list --installed 2>/dev/null | grep -qi "uiautomator2"; then
    echo "  Installing UiAutomator2 driver (one-time only)..."
    "$APPIUM_CMD" driver install uiautomator2 2>&1 | tee -a "$LOG"
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        echo "  FAIL  UiAutomator2 driver installation failed."
        echo "  Log: $LOG"
        read -r -p "  Press Enter to close... " _
        exit 1
    fi
    echo "  OK  UiAutomator2 driver installed."
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
echo "  (Close this window or run STOP.command to stop)"
echo ""

export AK_NO_BROWSER=1
"$PYTHON" "$A/web/app.py"

# ── Cleanup ─────────────────────────────────────────────────────────────────
kill "$APPIUM_PID" 2>/dev/null || true
[ -n "$CAFF_PID" ] && kill "$CAFF_PID" 2>/dev/null || true
echo ""
echo "  Web server stopped."
read -r -p "  Press Enter to close... " _
"""

STOP_COMMAND = """\
#!/bin/bash
# AccurKardia -- Stop all services
pkill -f "web/app.py" 2>/dev/null && echo "  Web server stopped." || echo "  Web server was not running."
pkill -f "appium" 2>/dev/null && echo "  Appium stopped." || echo "  Appium was not running."
pkill -f "caffeinate" 2>/dev/null
echo ""
echo "  Done."
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

    # bin/npm and bin/npx are symlinks in the tarball (→ lib/node_modules/npm/bin/).
    # When _add_dir copies them into the ZIP as regular files, Node.js resolves
    # require('../lib/cli.js') relative to bin/ instead of lib/node_modules/npm/bin/,
    # causing MODULE_NOT_FOUND. Replace them with correct wrapper scripts.
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
            info = zipfile.ZipInfo(arc_path)
            file_stat = f.stat()
            # Preserve executable bits
            unix_perm = stat.S_IMODE(file_stat.st_mode)
            info.external_attr = (unix_perm << 16) | 0x8000_0000
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, f.read_bytes())


def _add_script(zf: zipfile.ZipFile, arc_name: str, content: str):
    info = zipfile.ZipInfo(arc_name)
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
    name = f"AccurKardia-Mac-Standalone-v{VERSION}-{TODAY}.zip"
    path = out_dir / name

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)
        print(f"\nBuilding Mac standalone bundle → {path}\n")

        node_dir = _setup_node(tmp)
        _bundle_adb(tmp)

        print("  Packaging zip...", end=" ", flush=True)
        R = f"AccurKardia-Mac-Standalone-v{VERSION}"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            _add_script(zf, f"{R}/run.command", RUN_COMMAND)
            _add_script(zf, f"{R}/STOP.command", STOP_COMMAND)
            for fname in ["README_MAC_KR.txt", "README_MAC_EN.txt"]:
                if (ROOT / fname).exists():
                    zf.write(ROOT / fname, f"{R}/{fname}")

            P = f"{R}/automation"
            _add_dir(zf, node_dir,        f"{P}/node")
            _add_dir(zf, tmp / "runtime", f"{P}/runtime")

            zf.write(ROOT / "requirements.txt", f"{P}/requirements.txt")
            _add_dir(zf, ROOT / "src",     f"{P}/src")
            _add_dir(zf, ROOT / "web",     f"{P}/web")
            _add_dir(zf, ROOT / "scripts", f"{P}/scripts")
            _add_config(zf,                f"{P}/config")

        size_mb = path.stat().st_size // 1024 // 1024
        print(f"done\n\nMac Standalone ZIP: {path}  ({size_mb} MB)")
    return path


def main():
    ap = argparse.ArgumentParser(description="Build AccurKardia Mac Standalone ZIP")
    ap.add_argument("--out", default=str(Path.home() / "Desktop"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build(out)
    print("\nDone.")


if __name__ == "__main__":
    main()
