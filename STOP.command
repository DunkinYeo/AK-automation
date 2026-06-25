#!/bin/bash
# ============================================================
# AccurKardia -- Stop All Services
# STOP.command  (project root -- double-click to stop)
# ============================================================

chmod +x "$0" 2>/dev/null || true
cd "$(dirname "$0")" || true

echo ""
echo "  =============================================="
echo "  |  AccurKardia -- Stopping All Services...  |"
echo "  =============================================="
echo ""

# ── Stop web server (port 5003) ──────────────────────────────
echo "  Stopping web server (port 5003)..."
WEB_PIDS=$(lsof -ti tcp:5003 2>/dev/null)
if [ -n "$WEB_PIDS" ]; then
    echo "$WEB_PIDS" | xargs kill -9 2>/dev/null || true
    echo "  OK  Web server stopped."
else
    echo "  Web server was not running."
fi

# ── Stop Appium server (port 4723) ───────────────────────────
echo "  Stopping Appium server (port 4723)..."
APPIUM_PIDS=$(lsof -ti tcp:4723 2>/dev/null)
if [ -n "$APPIUM_PIDS" ]; then
    echo "$APPIUM_PIDS" | xargs kill -9 2>/dev/null || true
    echo "  OK  Appium server stopped."
else
    echo "  Appium server was not running."
fi

# ── Stop test runner (main.py) ────────────────────────────────
echo "  Stopping test runner (main.py)..."
MAIN_PIDS=$(pgrep -f "main.py" 2>/dev/null)
if [ -n "$MAIN_PIDS" ]; then
    echo "$MAIN_PIDS" | xargs kill -9 2>/dev/null || true
    echo "  OK  Test runner stopped."
else
    echo "  Test runner was not running."
fi

echo ""
echo "  =============================================="
echo "  |   All services stopped. Safe to close.    |"
echo "  =============================================="
echo ""
read -r -p "  Press Enter to close... " _
exit 0
