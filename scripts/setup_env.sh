#!/bin/bash
# ============================================================
# AccurKardia -- Environment Setup Logic
# scripts/setup_env.sh
#
#  Called by install.command (project root).
#  Do NOT run this file directly.
#
#  Steps:
#    [0] Homebrew
#    [1] Python 3.10+
#    [2] Node.js / npm
#    [3] ADB / platform-tools
#    [4] Java (JDK)
#    [5] Appium
#    [6] UiAutomator2 driver
#    [7] Python virtual environment + packages
#    [8] Create runtime folders
# ============================================================

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

cd "$(dirname "$0")/.." || {
    echo "  ERROR: Failed to change to project root."
    exit 1
}

if [ ! -f "web/app.py" ]; then
    echo ""
    echo "  ERROR  web/app.py not found."
    echo "  Run install.command from inside the AccurKardia-Automation folder."
    echo ""
    exit 1
fi

LOG_FILE="/tmp/ak_install_$(date +%Y%m%d_%H%M%S).log"
FAIL=0
PYTHON_EXE=""

echo "AccurKardia install started $(date)" >> "$LOG_FILE"

echo ""
echo "  =============================================="
echo "  |  AccurKardia -- Environment Setup         |"
echo "  =============================================="
echo ""
echo "  Log: $LOG_FILE"
echo ""

# ============================================================
# [0] Homebrew
# ============================================================
echo "[0] Homebrew..."
if ! command -v brew >/dev/null 2>&1; then
    echo "  Homebrew not found. Installing automatically..."
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    for _BREW_PREFIX in "/opt/homebrew" "/usr/local"; do
        if [ -f "$_BREW_PREFIX/bin/brew" ]; then
            eval "$("$_BREW_PREFIX/bin/brew" shellenv)" 2>/dev/null || true
            break
        fi
    done
    export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"
fi

if command -v brew >/dev/null 2>&1; then
    BREW_VER=$(brew --version 2>&1 | head -1)
    echo "  PASS  $BREW_VER"
    echo "[0] PASS: $BREW_VER" >> "$LOG_FILE"
else
    echo "  ERROR  Homebrew installation failed."
    echo "  Install manually: /bin/bash -c \"\$(curl -fsSL https://brew.sh/install.sh)\""
    echo "[0] FAIL: brew not found" >> "$LOG_FILE"
    exit 1
fi

# ============================================================
# [1] Python 3.10+
# ============================================================
echo "[1] Python 3.10+..."
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY_VERSION=$("$candidate" --version 2>&1 | awk '{print $2}')
        PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
        if [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 10 ] 2>/dev/null; then
            PYTHON_EXE="$candidate"
            echo "  PASS  Python $PY_VERSION ($candidate)"
            echo "[1] PASS: Python $PY_VERSION" >> "$LOG_FILE"
            break
        fi
    fi
done

if [ -z "$PYTHON_EXE" ]; then
    echo "  Python 3.10+ not found. Installing via Homebrew..."
    brew install python@3.12
    for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PY_VERSION=$("$candidate" --version 2>&1 | awk '{print $2}')
            PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
            if [ "$PY_MINOR" -ge 10 ] 2>/dev/null; then
                PYTHON_EXE="$candidate"
                echo "  PASS  Python $PY_VERSION ($candidate)"
                echo "[1] PASS after brew: $PY_VERSION" >> "$LOG_FILE"
                break
            fi
        fi
    done
    if [ -z "$PYTHON_EXE" ]; then
        echo "  ERROR  Python install failed."
        echo "[1] FAIL: python install failed" >> "$LOG_FILE"
        FAIL=1
    fi
fi

# ============================================================
# [2] Node.js / npm
# ============================================================
echo ""
echo "[2] Node.js / npm..."
if ! command -v node >/dev/null 2>&1; then
    echo "  Node.js not found. Installing via Homebrew..."
    brew install node
    if ! command -v node >/dev/null 2>&1; then
        echo "  ERROR  brew install node failed."
        echo "[2] FAIL: node install failed" >> "$LOG_FILE"
        FAIL=1
    else
        echo "  PASS  Node.js $(node --version 2>&1)"
        echo "[2] PASS after brew" >> "$LOG_FILE"
    fi
else
    echo "  PASS  Node.js $(node --version 2>&1)"
    echo "[2] PASS" >> "$LOG_FILE"
fi

# ============================================================
# [3] ADB / Android SDK
# ============================================================
echo ""
echo "[3] ADB / Android SDK..."
if command -v adb >/dev/null 2>&1; then
    echo "  PASS  $(adb version 2>&1 | head -1)"
    echo "[3] PASS" >> "$LOG_FILE"
else
    ADB_FOUND=0
    for SDK_PATH in \
        "$HOME/Library/Android/sdk" \
        "$HOME/Android/Sdk" \
        "/usr/local/share/android-sdk" \
        "/opt/android-sdk" \
        "/opt/homebrew/share/android-sdk"; do
        if [ -f "$SDK_PATH/platform-tools/adb" ]; then
            export ANDROID_HOME="$SDK_PATH"
            export PATH="$SDK_PATH/platform-tools:$PATH"
            ADB_FOUND=1
            echo "  PASS  $(adb version 2>&1 | head -1)"
            echo "[3] PASS: found at $SDK_PATH" >> "$LOG_FILE"
            break
        fi
    done
    if [ "$ADB_FOUND" -eq 0 ]; then
        echo "  ADB not found. Installing via Homebrew..."
        brew install android-platform-tools
        if command -v adb >/dev/null 2>&1; then
            echo "  PASS  $(adb version 2>&1 | head -1)"
            echo "[3] PASS after brew" >> "$LOG_FILE"
        else
            echo "  ERROR  brew install android-platform-tools failed."
            echo "[3] FAIL: adb install failed" >> "$LOG_FILE"
            FAIL=1
        fi
    fi
fi

# ============================================================
# [4] Java (JDK) — keytool / APK signing
# ============================================================
echo ""
echo "[4] Java (JDK)..."
JAVA_FOUND=0

# Already installed
if command -v java >/dev/null 2>&1; then
    _JAVA_HOME=$(/usr/libexec/java_home 2>/dev/null)
    if [ -n "$_JAVA_HOME" ] && [ -d "$_JAVA_HOME" ]; then
        export JAVA_HOME="$_JAVA_HOME"
        export PATH="$JAVA_HOME/bin:$PATH"
        echo "  PASS  Java $( java -version 2>&1 | head -1 )"
        echo "[4] PASS: $JAVA_HOME" >> "$LOG_FILE"
        JAVA_FOUND=1
    fi
fi

# Not found — install via Homebrew
if [ "$JAVA_FOUND" -eq 0 ]; then
    echo "  Java not found. Installing via Homebrew (openjdk)..."
    brew install openjdk --quiet
    if [ $? -eq 0 ]; then
        # Try /usr/libexec/java_home first
        _JAVA_HOME=$(/usr/libexec/java_home 2>/dev/null)
        # brew openjdk is keg-only; not registered with java_home — use direct path
        if [ -z "$_JAVA_HOME" ]; then
            for _p in \
                "$(brew --prefix openjdk 2>/dev/null)/libexec/openjdk.jdk/Contents/Home" \
                "/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"; do
                [ -d "$_p" ] && _JAVA_HOME="$_p" && break
            done
        fi
        if [ -n "$_JAVA_HOME" ] && [ -d "$_JAVA_HOME" ]; then
            export JAVA_HOME="$_JAVA_HOME"
            export PATH="$JAVA_HOME/bin:$PATH"
            echo "  PASS  Java installed: $JAVA_HOME"
            echo "[4] PASS after brew" >> "$LOG_FILE"
            JAVA_FOUND=1
        fi
    fi
fi

if [ "$JAVA_FOUND" -eq 0 ]; then
    echo "  WARN  Java installation failed. Install manually: brew install openjdk"
    echo "[4] WARN: java not found" >> "$LOG_FILE"
fi

# ============================================================
# [5] Appium
# ============================================================
echo ""
echo "[5] Appium..."
if command -v appium >/dev/null 2>&1; then
    echo "  PASS  Appium $(appium -v 2>&1 | head -1)"
    echo "[5] PASS" >> "$LOG_FILE"
else
    echo "  Appium not found. Installing globally via npm..."
    npm install -g appium
    if [ $? -ne 0 ]; then
        echo "  ERROR  Failed to install Appium. Try: sudo npm install -g appium"
        echo "[5] FAIL" >> "$LOG_FILE"
        FAIL=1
    else
        echo "  PASS  Appium $(appium -v 2>&1 | head -1)"
        echo "[5] PASS after npm" >> "$LOG_FILE"
    fi
fi

# ============================================================
# [6] UiAutomator2 driver
# ============================================================
echo ""
echo "[6] UiAutomator2 driver..."
if ! command -v appium >/dev/null 2>&1; then
    echo "  SKIP  Appium unavailable."
    echo "[6] SKIP" >> "$LOG_FILE"
else
    DRIVER_TMP="/tmp/ak_drivers_$$.txt"
    appium driver list --installed > "$DRIVER_TMP" 2>&1
    if grep -qi "uiautomator2" "$DRIVER_TMP"; then
        echo "  PASS  UiAutomator2 driver already installed."
        echo "[6] PASS" >> "$LOG_FILE"
    else
        echo "  UiAutomator2 not found. Installing..."
        appium driver install uiautomator2
        if [ $? -ne 0 ]; then
            echo "  ERROR  Failed. Try: appium driver install uiautomator2"
            echo "[6] FAIL" >> "$LOG_FILE"
            FAIL=1
        else
            echo "  PASS  UiAutomator2 driver installed."
            echo "[6] PASS" >> "$LOG_FILE"
        fi
    fi
    rm -f "$DRIVER_TMP"
fi

# ============================================================
# [7] Python virtual environment + packages
# ============================================================
echo ""
echo "[7] Python virtual environment..."
if [ -z "$PYTHON_EXE" ]; then
    echo "  SKIP  Python not available."
    echo "[7] SKIP" >> "$LOG_FILE"
elif [ ! -f "requirements.txt" ]; then
    echo "  ERROR  requirements.txt not found."
    echo "[7] FAIL: requirements.txt missing" >> "$LOG_FILE"
    FAIL=1
else
    if [ ! -f ".venv/bin/activate" ]; then
        echo "  Creating .venv..."
        "$PYTHON_EXE" -m venv .venv
        if [ $? -ne 0 ]; then
            echo "  ERROR  Failed to create .venv."
            echo "[7] FAIL: venv create" >> "$LOG_FILE"
            FAIL=1
        fi
    else
        echo "  INFO  .venv already exists."
    fi

    if [ "$FAIL" -eq 0 ]; then
        echo "  Installing Python packages..."
        .venv/bin/python -m pip install -r requirements.txt --quiet
        if [ $? -ne 0 ]; then
            echo "  ERROR  pip install failed."
            echo "[7] FAIL: pip install" >> "$LOG_FILE"
            FAIL=1
        else
            echo "  PASS  Python packages installed."
            echo "[7] PASS" >> "$LOG_FILE"
        fi
    fi
fi

# ============================================================
# [8] Create runtime folders
# ============================================================
echo ""
echo "[8] Runtime folders..."
mkdir -p logs runtime
echo "  PASS  logs/ and runtime/ are ready."
echo "[8] PASS" >> "$LOG_FILE"

# ============================================================
# Summary
# ============================================================
echo ""
echo "AccurKardia install ended $(date)" >> "$LOG_FILE"

if [ "$FAIL" -eq 1 ]; then
    echo "  =============================================="
    echo "  |   Setup encountered errors.              |"
    echo "  =============================================="
    echo ""
    echo "  Full log: $LOG_FILE"
    echo ""
    exit 1
fi

echo ""
echo "  --------------------------------------"
echo "  AccurKardia Automation Installed"
echo "  Next step: run run.command"
echo "  --------------------------------------"
echo ""
echo "  Full log: $LOG_FILE"
echo ""
echo "[DONE]" >> "$LOG_FILE"
exit 0
