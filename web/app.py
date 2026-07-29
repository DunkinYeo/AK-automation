"""
S-Patch Accurkardia Long-run Test — Web UI backend
Run:  python web/app.py   (from project root)
"""
import atexit
import datetime
import html as _html
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)

import yaml
from flask import Flask, jsonify, render_template, request, send_from_directory, Response

ROOT = Path(__file__).resolve().parent.parent
_INTERVAL_OVERRIDE = ROOT / "runtime" / "interval_override.json"
_INJECT_NOW_FILE   = ROOT / "runtime" / "inject_now.json"
sys.path.insert(0, str(ROOT))

ARTIFACTS_DIR = ROOT / "artifacts"

app = Flask(__name__)

PORT = 5003

# ── Shared state ─────────────────────────────────────────────────────────────
_state: dict = {"proc": None, "out_dir": None, "start_ts": None, "pid": None}

# ── Run-state persistence (survive web-server restart) ───────────────────────
# The run subprocess outlives a web-server restart; without this the dashboard
# loses track of it ("ghost run"). Zero impact when the file is absent: every
# code path behaves exactly as before.
_RUN_STATE_FILE = Path(__file__).resolve().parent.parent / "runtime" / "web_run_state.json"


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
        if sys.platform == "win32":
            # os.kill(pid, 0) does NOT mean "just check existence, no
            # signal" on Windows the way it does on POSIX — CPython's
            # Windows os.kill() always calls TerminateProcess(handle, sig),
            # even for sig=0. That means every previous call to this
            # function could have been silently KILLING a genuinely-alive
            # process as a side effect. Confirmed via a real Windows CI
            # failure (2026-07-29): a subprocess this function had just
            # "checked" turned up dead immediately after. OpenProcess with
            # only query rights + CloseHandle is the safe, side-effect-free
            # way to check existence on Windows. OpenProcess alone isn't
            # enough either, though — a just-exited process can still be
            # openable while any handle to it (e.g. subprocess.Popen's own)
            # remains open, confirmed live on windows-latest (2026-07-29):
            # OpenProcess succeeded for a pid whose Popen.wait() had already
            # returned. GetExitCodeProcess + STILL_ACTIVE is what actually
            # distinguishes "running" from "exited but not yet reaped".
            import ctypes
            import ctypes.wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.wintypes.DWORD()
                ok = ctypes.windll.kernel32.GetExitCodeProcess(
                    handle, ctypes.byref(exit_code))
                return bool(ok) and exit_code.value == STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _pid_is_our_run(pid) -> bool:
    """More than just alive — issue #20: a persisted pid can go stale (the
    process it named exited without the state file being cleared yet), and
    the OS can reuse that same pid number for a completely unrelated
    process. Confirm the pid is still actually running one of our entrypoints
    before trusting it enough to re-attach to it or send it a kill signal."""
    if not _pid_alive(pid):
        return False
    if sys.platform == "win32":
        # `ps` doesn't exist on Windows (issue #28) — the check silently
        # degraded to alive-only there, exactly the risk this function
        # exists to close. Get-CimInstance is the still-supported way to
        # get a process's full command line (wmic is being phased out —
        # confirmed absent entirely on windows-latest GH Actions runners,
        # 2026-07-29).
        cmd = ["powershell", "-NoProfile", "-Command",
               f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine']
    else:
        cmd = ["ps", "-p", str(pid), "-o", "command="]
    proc = None
    try:
        # Popen (not subprocess.run()) so any exception — including the
        # BaseException below — can still explicitly kill/reap the child
        # instead of leaking it.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, _ = proc.communicate(timeout=5)
        # Windows CommandLine comes back with backslashes (issue #31) —
        # normalize before matching so a real Windows run doesn't fail its
        # own identity check.
        out = out.replace("\\", "/")
        # Match this installation's actual entrypoint path, not a bare
        # "src/main.py" substring — that matched ANY project with a
        # src/main.py anywhere in its path (e.g. an unrelated /tmp/foo/
        # src/main.py), which is exactly the kind of false-positive #20/#28
        # exist to prevent. api_start spawns with str(ROOT / "src" / entry),
        # so comparing against that same construction is the correct match.
        our_paths = (
            str(ROOT / "src" / "main.py").replace("\\", "/"),
            str(ROOT / "src" / "main_ios.py").replace("\\", "/"),
        )
        return any(p in out for p in our_paths)
    except BaseException:
        # Deliberately BaseException, not Exception: reproduced live on
        # windows-latest (2026-07-29) — spawning the PowerShell subprocess
        # under GitHub Actions' `pwsh` step wrapper raises a genuine
        # KeyboardInterrupt from inside communicate()'s thread startup,
        # which `except Exception` does not catch.
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        # Fail closed, not open (issue #32): this function gates destructive
        # actions (/api/stop sends a kill signal to whatever pid this says
        # is ours). Couldn't verify == treat it as not ours — worst case is
        # an inconvenience (re-attach/Stop silently no-ops on a genuinely
        # good run), never "sent a kill signal to an unrelated process".
        return False


def _run_already_active() -> bool:
    """True if a test process is currently running — either tracked via
    Popen (started by this server process) or re-attached after a web
    server restart, where `_state["proc"]` is None but `_state["pid"]`
    is still a live process (issue #16: /api/start's guard previously
    only checked `proc`, so Start could spawn a second automation
    process onto the same device after a server restart)."""
    proc = _state["proc"]
    if proc and proc.poll() is None:
        return True
    pid = _state.get("pid")
    # Identity-checked, not just alive (issue #33 — same reasoning as
    # #20/#30): a stale/reused pid must not block a legitimate Start by
    # looking like an already-active run.
    return bool(pid and _pid_is_our_run(pid))


def _persist_run_state(pid: int, start_ts: float, out_dir: str | None = None) -> None:
    try:
        _RUN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RUN_STATE_FILE.write_text(json.dumps(
            {"pid": pid, "start_ts": start_ts, "out_dir": out_dir}))
    except Exception:
        pass


def _clear_run_state() -> None:
    try:
        if _RUN_STATE_FILE.exists():
            _RUN_STATE_FILE.unlink()
    except Exception:
        pass


def _load_persisted_run() -> None:
    """On server boot: re-attach to a run started by a previous server process."""
    try:
        if not _RUN_STATE_FILE.exists():
            return
        saved = json.loads(_RUN_STATE_FILE.read_text())
        pid, start_ts = saved.get("pid"), saved.get("start_ts")
        if pid and start_ts and _pid_is_our_run(pid):
            _state["pid"] = int(pid)
            _state["start_ts"] = float(start_ts)
            out_dir = saved.get("out_dir")
            if out_dir and Path(out_dir).is_dir():
                _state["out_dir"] = out_dir
            print(f"[run-state] Re-attached to running test (pid={pid})", flush=True)
        else:
            _clear_run_state()
    except Exception:
        pass


_load_persisted_run()
_lock = threading.Lock()

# ── Regression state ──────────────────────────────────────────────────────────
_reg_state: dict = {"proc": None, "log": [], "results": None, "done": False, "exit_code": None}
_reg_lock = threading.Lock()

# ── Hub state (team dashboard) ────────────────────────────────────────────────
_hub_sessions: dict = {}
_hub_lock = threading.Lock()

REG_RESULT_JSON = str(ROOT / "output" / "_reg_results.json")
REG_SUITES = "main,diary,menu-study"


def _stream_reg_output(proc):
    for line in proc.stdout:
        with _reg_lock:
            _reg_state["log"].append(line.rstrip())
    proc.wait()
    with _reg_lock:
        _reg_state["exit_code"] = proc.returncode
        _reg_state["done"] = True
        try:
            p = Path(REG_RESULT_JSON)
            if p.exists():
                _reg_state["results"] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass

# ── AK selectors (English only) ───────────────────────────────────────────────
AK_SELECTORS = {
    "symptom_add_text":        "Log Symptoms",
    "main_screen_text":        "My Study Progress",
    "log_symptoms_button_text":"Log Symptoms",
    "log_symptoms_submit_text":"Save",
    "symptom_section_text":    "Symptom",
    "cannot_find_patch_title": "Cannot find your S-Patch",
    "reset_patch_title":       "Reset your S-Patch",
    "popup_ok_button_text":    "Ok",
    "connect_button_text":     "Connect",
    "serial_input_hint":       "Enter the Serial Number here.",
    "start_study_button_text": "Start Study",
    "device_status_tab_text":  "Device Status",
    "realtime_ecg_tab_text":   "Real-time ECG",
    "setting_text":            "Setting",
}

# iOS selectors — main screen has no "Add Diary"; "Log Symptoms" is the
# main-screen indicator (see config/accurkardia_ios.yaml)
AK_SELECTORS_IOS = {
    "symptom_add_text":         "Log Symptoms",
    "main_screen_text":         "My Study Progress",
    "log_symptoms_button_text": "Log Symptoms",
    "connect_button_text":      "Connect",
    "start_study_button_text":  "Start Study",
}

# iOS device constants (iPhone 13 mini test device)
IOS_DEFAULTS = {
    "appium_server_url":   "http://127.0.0.1:4723",
    "platform_version":    "18.6",
    "device_name":         "Wellysis iPhone 13 mini",
    "bundle_id":           "com.wellysis.accurkardia.accurkardia",
    "no_reset":            True,
    "new_command_timeout": 3600,
    "xcode_org_id":        "9538X2C925",
    "xcode_signing_id":    "Apple Development",
    "wda_local_port":      8100,
    "wda_launch_timeout":  120000,
    "show_xcode_log":      True,
}

AK_SYMPTOMS = [
    "Chest pain / discomfort",
    "Shortness of breath",
    "Dizziness",
    "Fainting",
    "Palpitations / Heart pounding",
    "Nausea",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_devices() -> list[str]:
    try:
        r = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
        return [
            line.split("\t")[0].strip()
            for line in r.stdout.splitlines()[1:]
            if "\t" in line and line.split("\t")[1].strip() == "device"
        ]
    except Exception:
        return []


def get_ios_devices() -> list[str]:
    """List connected iOS device UDIDs (libimobiledevice, else pymobiledevice3)."""
    try:
        r = subprocess.run(["idevice_id", "-l"], capture_output=True, text=True, timeout=5)
        devices = [line.strip() for line in r.stdout.splitlines() if line.strip()]
        if devices:
            return devices
    except Exception:
        pass
    # pip-only fallback (testers won't have brew libimobiledevice)
    try:
        r = subprocess.run([sys.executable, "-m", "pymobiledevice3", "usbmux", "list"],
                           capture_output=True, text=True, timeout=10)
        import json as _json
        data = _json.loads(r.stdout or "[]")
        return [d.get("UniqueDeviceID", "") for d in data if d.get("UniqueDeviceID")]
    except Exception:
        return []


_appium_cache: dict = {"ok": False, "ts": 0.0}

def appium_ok(force: bool = False) -> bool:
    if not force and time.time() - _appium_cache["ts"] < 10:
        return _appium_cache["ok"]
    try:
        with urllib.request.urlopen("http://127.0.0.1:4723/status", timeout=2) as r:
            result = json.loads(r.read()).get("value", {}).get("ready", False)
    except Exception:
        result = False
    _appium_cache["ok"] = result
    _appium_cache["ts"] = time.time()
    return result


def read_events(out_dir: str | None) -> list[dict]:
    if not out_dir:
        return []
    p = Path(out_dir) / "events.jsonl"
    if not p.exists():
        return []
    events = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                ev = json.loads(line)
                # iOS runs emit "<name>_ios" events — normalize so the
                # dashboard (suite cards, log, progress) renders both platforms
                name = ev.get("event", "")
                if name.endswith("_ios"):
                    ev["event"] = name[:-4]
                events.append(ev)
            except Exception:
                pass
    return events


def _terminal_event(events: list[dict]) -> str | None:
    """
    Scan back to the most recent run_start looking for a terminal event.
    Returns 'run_complete', 'run_failed', or None (still running / unknown).
    A terminal event isn't always the very last line — restore events
    (e.g. screen_timeout_set) land after run_complete, which left finished
    runs stuck showing "running" in both /api/status and the team dashboard
    mirror (2026-07-20, 2026-07-22 — same bug, two call sites).
    """
    for e in reversed(events):
        n = e.get("event", "")
        if n in ("run_complete", "run_failed"):
            return n
        if n == "run_start":
            break
    return None


def find_latest_output_dir(since: float) -> str | None:
    out = ROOT / "output"
    if not out.exists():
        return None
    dirs = [d for d in out.iterdir() if d.is_dir() and d.stat().st_mtime >= since - 1]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return str(dirs[0]) if dirs else None


def _find_latest_output_dir() -> str | None:
    out = ROOT / "output"
    if not out.exists():
        return None
    dirs = sorted(
        (d for d in out.iterdir() if d.is_dir() and d.name not in ("regression", "tmp")),
        key=lambda d: d.stat().st_mtime, reverse=True,
    )
    return str(dirs[0]) if dirs else None


def _sync_localhost_session():
    """Mirror the most recent local AK run into _hub_sessions['Localhost']."""
    while True:
        time.sleep(4)
        try:
            with _lock:
                proc     = _state["proc"]
                out_dir  = _state["out_dir"]
                start_ts = _state["start_ts"]
                if not out_dir and start_ts:
                    found = find_latest_output_dir(start_ts)
                    if found:
                        _state["out_dir"] = found
                        out_dir = found
            if not out_dir:
                out_dir = _find_latest_output_dir()
            events = read_events(out_dir) if out_dir else []
            if not events:
                continue

            device = ""
            duration_hours = None
            interval_hours = None
            last_ts = ""
            for e in events:
                ev   = e.get("event", "")
                data = e.get("data", {})
                if ev == "device_info":
                    model   = data.get("model", "")
                    android = data.get("android_version", "")
                    ios     = data.get("ios_version", "")
                    udid    = data.get("udid", "")
                    ver     = (f" · iOS {ios}" if ios
                               else f" · Android {android}" if android else "")
                    device  = f"{model}{ver} ({udid})" if model else udid
                elif ev == "run_start":
                    duration_hours = duration_hours or data.get("duration_hours")
                    interval_hours = interval_hours or data.get("interval_hours")
                last_ts = e.get("ts", last_ts)

            terminal = _terminal_event(events)
            status = "done" if terminal == "run_complete" else "failed" if terminal == "run_failed" else "running"

            # Auto-save report when test completes
            if status in ("done", "failed") and out_dir:
                report_path = Path(out_dir) / "report.html"
                if not report_path.exists():
                    try:
                        report_path.write_text(_build_report_html(events), encoding="utf-8")
                        log.info("[report] Auto-saved to %s", report_path)
                    except Exception:
                        pass

            with _hub_lock:
                _hub_sessions["Localhost"] = {
                    "events": events[-200:], "last_seen": last_ts,
                    "status": status, "device": device,
                    "duration_hours": duration_hours, "interval_hours": interval_hours,
                }
        except Exception:
            pass


threading.Thread(target=_sync_localhost_session, daemon=True).start()


def _appium_watchdog():
    """Restart Appium automatically if it dies while a test is running."""
    while True:
        time.sleep(30)
        try:
            with _lock:
                proc = _state.get("proc")
                running = bool(proc and proc.poll() is None)
            if not running:
                continue
            if appium_ok(force=True):
                continue
            appium_cmd = _find_appium_cmd()
            if not appium_cmd:
                continue
            print("[watchdog] Appium down — restarting...", flush=True)
            subprocess.Popen(
                [appium_cmd, "--port", "4723"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(3)
            if appium_ok(force=True):
                print("[watchdog] Appium restarted successfully", flush=True)
            else:
                print("[watchdog] Appium restart failed", flush=True)
        except Exception:
            pass


threading.Thread(target=_appium_watchdog, daemon=True).start()


def _make_auto_open_watcher():
    """Auto-open the web report when the current run reaches a terminal
    state (run_complete / run_failed — the until-study-ends auto mode
    always logs run_complete right after its own run_ended_study_complete,
    so this covers a clean finish, a crash, and auto-mode completion
    alike). A tester watching an unattended long run otherwise has no way
    to know it ended unless they're actively watching the dashboard tab
    (2026-07-29).

    Controlled by AK_NO_AUTO_REPORT_OPEN, deliberately NOT AK_NO_BROWSER
    (review 2026-07-29): run.command/run.bat/the dist-bundle build scripts
    all export AK_NO_BROWSER=1 unconditionally before starting the server
    — they suppress the built-in startup-open timer because they run their
    own healthcheck-polled browser open instead, not because testers don't
    want a browser opened at all. Reusing that same variable here would
    have silently disabled this feature for every real distributed build,
    only ever firing when a developer runs `python web/app.py` directly.

    Returns (step, loop): `step()` runs one poll iteration synchronously
    (returns True if it just opened the browser) so the transition logic
    can be unit-tested without waiting on the real 5s loop; `loop()` is
    what actually runs forever in the background thread.
    """
    state = {"known_out_dir": None, "was_terminal": True}  # True: don't
    # fire for whatever's already there the first time this notices an
    # out_dir (server boot, or a run already finished) — only a live
    # non-terminal → terminal transition should open a browser.

    def step() -> bool:
        try:
            with _lock:
                out_dir = _state.get("out_dir")
            if out_dir != state["known_out_dir"]:
                state["known_out_dir"] = out_dir
                events = read_events(out_dir) if out_dir else []
                state["was_terminal"] = _terminal_event(events) is not None
                return False
            if not out_dir or state["was_terminal"]:
                return False
            if _terminal_event(read_events(out_dir)) is not None:
                state["was_terminal"] = True
                if not os.environ.get("AK_NO_AUTO_REPORT_OPEN"):
                    webbrowser.open(f"http://localhost:{PORT}/api/report")
                return True
        except Exception:
            pass
        return False

    def loop():
        while True:
            time.sleep(5)
            step()

    return step, loop


_auto_open_step, _auto_open_loop = _make_auto_open_watcher()


def _kill_proc():
    with _lock:
        proc = _state.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                # 15s parity with /api/stop — the run's finally needs time to
                # restore the device screen timeout (review 2026-07-14)
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        # Re-attached run (pid only, no Popen handle) is NOT killed on server
        # exit — it keeps running and still owns the device screen timeout.
        # Identity-checked, not just alive (issue #30 — #20 missed this
        # 4th call site): a stale/reused pid must not suppress the
        # screen-timeout backstop below by looking like a live run.
        run_alive = bool(_state.get("pid") and _pid_is_our_run(_state["pid"]))
    # Same backstop as /api/stop: web-server restart/shutdown that takes the
    # run down with it must not leave the 24h marker on the device. Skipped
    # while a run is still alive — resetting the timeout under a live run
    # was observed 2026-07-16 when a test import fired this at exit.
    if not run_alive:
        _screen_timeout_backstop()


_exit_hooks_registered = False


def _register_exit_hooks():
    """
    Register the shutdown cleanup only in the process actually running the
    server — called once from `if __name__ == "__main__"`, not at plain
    import time, so an importer (smoke_test.py, ad-hoc scripts using the
    test client) never fires the screen-timeout backstop on exit and resets
    the timeout under a live run (observed 2026-07-16). Must be called from
    the main thread: `signal.signal` raises ValueError anywhere else, and
    calling this from inside a request handler (Flask runs each request in
    its own thread under `threaded=True`) crashed every single /api/start
    call with a 500 — the run still started (Popen already ran by that
    point), but the exit-hook registration silently never happened, so the
    web server dying never cleaned up its child run (found 2026-07-28
    while validating issue #16).
    """
    global _exit_hooks_registered
    if _exit_hooks_registered:
        return
    _exit_hooks_registered = True
    atexit.register(_kill_proc)
    signal.signal(signal.SIGTERM, lambda *_: (_kill_proc(), sys.exit(0)))


def _get_lan_ip() -> str:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return ""


def _find_appium_cmd() -> str | None:
    import shutil, os
    from pathlib import Path
    # Bundled standalone path: web/app.py → web/ → automation/ → appium/
    here = Path(__file__).resolve().parent.parent  # automation/
    if sys.platform == "win32":
        bundled = here / "appium" / "node_modules" / ".bin" / "appium.cmd"
    else:
        bundled = here / "appium" / "bin" / "appium"
    if bundled.is_file():
        return str(bundled)
    cmd = shutil.which("appium")
    if cmd:
        return cmd
    if sys.platform == "win32":
        candidate = os.path.join(os.environ.get("APPDATA", ""), "npm", "appium.cmd")
        if os.path.isfile(candidate):
            return candidate
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


def get_cached_wifi() -> str:
    """Return cached WiFi address from runtime/adb_wifi_device.json written by run.command."""
    import json as _json
    cache = ROOT / "runtime" / "adb_wifi_device.json"
    try:
        d = _json.loads(cache.read_text())
        ip = d.get("wifi_ip", "")
        port = d.get("tcp_port", 5555)
        return f"{ip}:{port}" if ip else ""
    except Exception:
        return ""


@app.route("/api/init")
def api_init():
    return jsonify({"devices": get_devices(), "ios_devices": get_ios_devices(),
                    "appium": appium_ok(), "cached_wifi": get_cached_wifi()})


@app.route("/api/detect-wifi", methods=["POST"])
def api_detect_wifi():
    """Detect WiFi IPs from every USB-connected ADB device, save cache, return addresses."""
    import re
    devices = get_devices()
    usb_serials = [d for d in devices if ":" not in d]
    if not usb_serials:
        return jsonify({"error": "No USB device connected"}), 400
    detected: list[dict] = []
    errors: dict[str, str] = {}
    for usb_serial in usb_serials:
        try:
            r = subprocess.run(
                ["adb", "-s", usb_serial, "shell", "ip", "route"],
                capture_output=True, text=True, timeout=10,
            )
            m = re.search(r"src (\d+\.\d+\.\d+\.\d+)", r.stdout)
            if not m:
                errors[usb_serial] = "Could not determine WiFi IP from device"
                continue
            wifi_ip = m.group(1)
            subprocess.run(["adb", "-s", usb_serial, "tcpip", "5555"], capture_output=True, timeout=10)
            time.sleep(1)
            # A dozing phone's WiFi rejects the first TCP attempts ("No route
            # to host", observed 2026-07-20) — ping to wake the radio, retry,
            # and only report devices whose connect actually succeeded.
            ping_cmd = (["ping", "-n", "1", "-w", "2000", wifi_ip]
                        if os.name == "nt" else ["ping", "-c", "1", wifi_ip])
            connected, out = False, ""
            for _attempt in range(3):
                subprocess.run(ping_cmd, capture_output=True, timeout=6)
                r2 = subprocess.run(["adb", "connect", f"{wifi_ip}:5555"],
                                    capture_output=True, text=True, timeout=10)
                out = (r2.stdout + r2.stderr).strip()
                if "connected" in out.lower():
                    connected = True
                    break
                time.sleep(2)
            if not connected:
                errors[usb_serial] = f"adb connect failed: {out[:80]}"
                continue
            detected.append({"device_id": usb_serial, "wifi_ip": wifi_ip, "tcp_port": 5555})
        except Exception as e:
            errors[usb_serial] = str(e)
    if not detected:
        return jsonify({"error": "; ".join(f"{k}: {v}" for k, v in errors.items())}), 400
    cache = ROOT / "runtime" / "adb_wifi_device.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    primary = detected[0]
    cache.write_text(json.dumps({
        # Top-level single-device keys are the legacy format read by
        # src/driver.py _read_wifi_cache() and get_cached_wifi() — keep them.
        "device_id": primary["device_id"],
        "wifi_ip": primary["wifi_ip"],
        "tcp_port": primary["tcp_port"],
        "devices": detected,
        "updated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }))
    return jsonify({
        "wifi_addr": f"{primary['wifi_ip']}:{primary['tcp_port']}",
        "wifi_addrs": [f"{d['wifi_ip']}:{d['tcp_port']}" for d in detected],
        "errors": errors or None,
    })


@app.route("/api/local-ip")
def api_local_ip():
    ip = _get_lan_ip()
    try:
        port = int(request.host.split(":")[-1])
    except Exception:
        port = PORT
    return jsonify({"ip": ip, "port": port})


@app.route("/api/appium/start", methods=["POST"])
def api_appium_start():
    appium_cmd = _find_appium_cmd()
    if not appium_cmd:
        return jsonify({"error": "appium command not found. Run install.command first."}), 500
    try:
        subprocess.Popen(
            [appium_cmd, "--port", "4723"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2.5)
        return jsonify({"ok": True, "running": appium_ok()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def api_status():
    with _lock:
        proc     = _state["proc"]
        out_dir  = _state["out_dir"]
        start_ts = _state["start_ts"]
        running  = bool(proc and proc.poll() is None)

        # Re-attached run (server restarted; no Popen handle, pid only)
        if not running and not proc and _state.get("pid"):
            if _pid_is_our_run(_state["pid"]):
                running = True
            else:
                _state["pid"] = None
                _clear_run_state()

        if not out_dir and start_ts:
            found = find_latest_output_dir(start_ts)
            if found:
                _state["out_dir"] = found
                out_dir = found
                # Keep the persisted state exact so a restarted server binds
                # to this run's real output dir, not a newer unrelated one
                if _state.get("pid"):
                    _persist_run_state(_state["pid"], start_ts, found)

        events    = read_events(out_dir)
        # A tracked proc that has actually exited is authoritative — never
        # let it get papered over as "running" below just because no
        # terminal event was logged (issue #21: a SIGKILL/segfault skips
        # both run_complete and run_failed, so _terminal_event() alone
        # can't tell "still running" from "died without a trace").
        proc_confirmed_dead = bool(proc and proc.poll() is not None)
        terminal = _terminal_event(events) if events else None
        # If test process isn't tracked but events exist and look active, treat as running
        if not running and not proc_confirmed_dead and events and (proc or start_ts):
            if terminal is None:
                running = True
        elif proc_confirmed_dead and terminal is None and out_dir:
            # Record the abnormal exit so it shows up in the report/log
            # instead of silently vanishing with no trace.
            synthetic = {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "event": "run_failed",
                "data": {"error": f"process exited unexpectedly (code {proc.poll()})"},
            }
            try:
                with open(Path(out_dir) / "events.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(synthetic, ensure_ascii=False) + "\n")
                events.append(synthetic)
            except Exception:
                pass
        elif proc_confirmed_dead and terminal is not None:
            # issue #20: this tracked run genuinely finished (naturally or
            # crashed-then-logged) — clear the persisted pid pointer now
            # instead of leaving it stale until the next server restart
            # happens to notice the pid is dead. Narrows the window where a
            # reused pid could be mistaken for this run.
            _clear_run_state()
        exit_code = proc.poll() if proc else None

        return jsonify({
            "running":   running,
            "exit_code": exit_code,
            "appium":    appium_ok(),
            "events":    events,
        })


@app.route("/api/start", methods=["POST"])
def api_start():
    with _lock:
        if _run_already_active():
            return jsonify({"error": "Already running."}), 400

        data     = request.json or {}
        device   = data.get("device", "")
        serial   = data.get("serial", "").strip()
        platform = (data.get("platform") or "android").lower()

        # Optional WiFi ADB connect (Android only)
        wifi_addr = (data.get("wifi_addr") or "").strip()
        if platform == "android" and data.get("wifi_mode") and wifi_addr:
            try:
                result = subprocess.run(
                    ["adb", "connect", wifi_addr],
                    capture_output=True, text=True, timeout=10,
                )
                output = (result.stdout + result.stderr).strip()
                if "connected" not in output.lower() and "already connected" not in output.lower():
                    return jsonify({"error": f"ADB connect failed: {output}"}), 400
                if not device:
                    device = wifi_addr
            except Exception as e:
                return jsonify({"error": f"ADB connect error: {e}"}), 500

        symptoms = data.get("symptoms") or AK_SYMPTOMS[:3]
        slack_webhook = (data.get("slack_webhook") or "").strip()

        run_section = {
            "name":                          data.get("run_name") or "ak_run",
            "duration_hours":                int(data.get("duration_hours", 72)),
            "until_study_end":               bool(data.get("until_study_end")),
            "symptom_interval_hours":        float(data.get("interval_hours", 1)),
            "start_immediately":             True,
            "jitter_seconds":                0,
            "quiet_hours":                   {"start": 2, "end": 6},
            "bt_disconnect_interval_hours":  float(data.get("bt_disconnect_interval_hours", 1)),
            "bt_disconnect_minutes":         float(data.get("bt_disconnect_minutes", 10)),
            "airplane_mode_interval_hours":  float(data.get("airplane_mode_interval_hours", 1)),
            "airplane_mode_minutes":         float(data.get("airplane_mode_minutes", 5)),
        }
        common = {
            "recovery": {"cooldown_seconds_between_steps": 30},
            "symptom_catalog": {"symptoms": symptoms},
            "slack": {
                "enabled":     bool(slack_webhook),
                "webhook_url": slack_webhook,
                "mention":     (data.get("slack_mention") or "").strip(),
            },
        }

        if platform == "ios":
            cfg = {
                "platform": "ios",
                "run": run_section,
                "ios": {
                    **IOS_DEFAULTS,
                    "udid":               device,
                    "test_serial_number": serial,
                },
                "selectors": {"ios": AK_SELECTORS_IOS},
                **common,
            }
            entry = "main_ios.py"
        else:
            cfg = {
                "platform": "android",
                "run": run_section,
                "android": {
                    "appium_server_url":   "http://127.0.0.1:4723",
                    "device_name":         device,
                    "udid":                device,
                    "test_serial_number":  serial,
                    "search_serial":       serial,
                    "app_package":         "com.wellysis.accurkardia.accurkardia.mobile",
                    "app_activity":        "com.wellysis.accurkardia.accurkardia.mobile.MainActivity",
                    "no_reset":            True,
                    "new_command_timeout": 3600,
                },
                "selectors": {"android": AK_SELECTORS},
                **common,
            }
            entry = "main.py"

        cfg_path = ROOT / "config" / "_web_run.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

        start_ts = time.time()
        _state["start_ts"] = start_ts
        _state["out_dir"]  = None
        cmd = [sys.executable, str(ROOT / "src" / entry), "--config", str(cfg_path)]
        if data.get("skip_regression"):
            cmd.append("--skip-regression")
        _state["proc"]     = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
        )
        _state["pid"] = _state["proc"].pid
        _persist_run_state(_state["proc"].pid, start_ts)
        _clear_interval_override()
        return jsonify({"ok": True})


def _screen_timeout_backstop():
    """
    If a hard-killed run left the 24h screen-timeout marker on the device,
    restore the exact value saved by that run. Covers the SIGKILL window the
    run's own finally-restore cannot (review 2026-07-14). Idempotent — only
    acts when both the marker value and runtime evidence are present.
    """
    try:
        cfg = yaml.safe_load((ROOT / "config" / "_web_run.yaml").read_text(encoding="utf-8")) or {}
        if (cfg.get("platform") or "android") != "android":
            return
        udid = (cfg.get("android") or {}).get("udid", "")
        if not udid:
            return
        orig_file = ROOT / "runtime" / "screen_timeout_orig.json"
        try:
            saved = json.loads(orig_file.read_text(encoding="utf-8"))
            orig = str(saved.get("orig", ""))
        except Exception:
            return
        if not orig.isdigit():
            return

        adb = ["adb", "-s", udid, "shell", "settings"]
        r = subprocess.run(adb + ["get", "system", "screen_off_timeout"],
                           capture_output=True, text=True, timeout=5)
        if r.stdout.strip() == "86400000":
            # Exact original saved by the run at set-time. Without this
            # evidence, do not treat 24h as pollution; it may be tester intent.
            subprocess.run(adb + ["put", "system", "screen_off_timeout", orig],
                           capture_output=True, timeout=5)
            # Verify before deleting the orig file — a silently failed put
            # must keep it for the next backstop attempt (review parity
            # with the run-side fix)
            chk = subprocess.run(adb + ["get", "system", "screen_off_timeout"],
                                 capture_output=True, text=True, timeout=5)
            if chk.stdout.strip() == orig:
                try:
                    orig_file.unlink()
                except Exception:
                    pass
                print(f"[stop] screen-timeout backstop: marker found → restored {orig}", flush=True)
            else:
                print(f"[stop] screen-timeout backstop: restore to {orig} NOT confirmed — keeping orig file", flush=True)
    except Exception:
        pass


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with _lock:
        proc = _state["proc"]
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                # 15s (was 5): the run's finally needs time for the screen-
                # timeout restore and driver teardown before we hard-kill
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        elif not proc and _state.get("pid") and _pid_is_our_run(_state["pid"]):
            # Re-attached run (no Popen handle): same SIGTERM → wait → SIGKILL.
            # Identity-checked (not just alive) — issue #20: a stale pid must
            # never get a kill signal meant for a run that already ended.
            pid = _state["pid"]
            try:
                os.kill(pid, signal.SIGTERM)
                deadline = time.time() + 15
                while time.time() < deadline and _pid_alive(pid):
                    time.sleep(0.5)
                if _pid_alive(pid):
                    os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        _state["proc"]     = None
        _state["start_ts"] = None
        _state["out_dir"]  = None
        _state["pid"]      = None
    _clear_run_state()
    _clear_interval_override()
    _screen_timeout_backstop()
    return jsonify({"ok": True})


def _clear_interval_override():
    try:
        p = _INTERVAL_OVERRIDE
        if p.exists():
            p.unlink()
    except Exception:
        pass


@app.route("/api/set-interval", methods=["POST"])
def api_set_interval():
    data = request.json or {}
    hours = float(data.get("interval_hours", 0))
    if hours <= 0:
        return jsonify({"error": "interval_hours must be > 0"}), 400
    try:
        p = _INTERVAL_OVERRIDE
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps({"interval_hours": hours}))
        print(f"[set-interval] Override set to {hours:.2f}h", flush=True)
        return jsonify({"ok": True, "interval_hours": hours})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/inject-now", methods=["POST"])
def api_inject_now():
    with _lock:
        proc_alive = _state["proc"] and _state["proc"].poll() is None
        # Identity-checked, not just alive (issue #33).
        pid_alive = not _state["proc"] and _state.get("pid") and _pid_is_our_run(_state["pid"])
        if not (proc_alive or pid_alive):
            return jsonify({"error": "No test running"}), 400
    try:
        _INJECT_NOW_FILE.parent.mkdir(exist_ok=True)
        _INJECT_NOW_FILE.write_text("{}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Regression ────────────────────────────────────────────────────────────────

@app.route("/api/regression/start", methods=["POST"])
def api_regression_start():
    with _reg_lock:
        if _reg_state["proc"] and _reg_state["proc"].poll() is None:
            return jsonify({"error": "Regression already running"}), 400

    data   = request.json or {}
    device = data.get("device", "")
    serial = data.get("serial", "").strip()

    # WiFi ADB connect (same as api_start)
    wifi_addr = (data.get("wifi_addr") or "").strip()
    if data.get("wifi_mode") and wifi_addr:
        try:
            result = subprocess.run(
                ["adb", "connect", wifi_addr],
                capture_output=True, text=True, timeout=10,
            )
            output = (result.stdout + result.stderr).strip()
            if "connected" not in output.lower() and "already connected" not in output.lower():
                return jsonify({"error": f"ADB connect failed: {output}"}), 400
            if not device:
                device = wifi_addr
        except Exception as e:
            return jsonify({"error": f"ADB connect error: {e}"}), 500

    cfg = {
        "platform": "android",
        "run": {"name": "regression", "duration_hours": 1},
        "android": {
            "appium_server_url":   "http://127.0.0.1:4723",
            "device_name":         device,
            "udid":                device,
            "test_serial_number":  serial,
            "search_serial":       serial,
            "app_package":         "com.wellysis.accurkardia.accurkardia.mobile",
            "app_activity":        "com.wellysis.accurkardia.accurkardia.mobile.MainActivity",
            "no_reset":            True,
            "new_command_timeout": 3600,
        },
        "selectors": {"android": AK_SELECTORS},
    }

    cfg_path = ROOT / "config" / "_web_reg.yaml"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

    import os as _os
    _os.makedirs(str(ROOT / "output"), exist_ok=True)
    # Clear old result file
    try:
        Path(REG_RESULT_JSON).unlink(missing_ok=True)
    except Exception:
        pass

    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "src" / "run_regression.py"),
         "--config", str(cfg_path),
         "--suite", REG_SUITES,
         "--result-json", REG_RESULT_JSON],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(ROOT),
    )
    with _reg_lock:
        _reg_state["proc"]      = proc
        _reg_state["log"]       = []
        _reg_state["results"]   = None
        _reg_state["done"]      = False
        _reg_state["exit_code"] = None

    threading.Thread(target=_stream_reg_output, args=(proc,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/regression/status")
def api_regression_status():
    with _reg_lock:
        proc    = _reg_state["proc"]
        running = bool(proc and proc.poll() is None)
        return jsonify({
            "running":   running,
            "done":      _reg_state["done"],
            "exit_code": _reg_state["exit_code"],
            "log":       _reg_state["log"][-200:],
            "results":   _reg_state["results"],
        })


# ── Team dashboard ───────────────────────────────────────────────────────────

@app.route("/team")
def team():
    return render_template("team_ak.html")


@app.route("/api/hub/events", methods=["POST"])
def api_hub_events():
    """Receive a single event from a tester's running automation."""
    data    = request.json or {}
    tester  = data.get("tester_name") or "unknown"
    event   = data.get("event") or ""
    # iOS runs emit "<name>_ios" events — normalize like read_events() does
    # so status/device/duration match both platforms
    if event.endswith("_ios"):
        event = event[:-4]
    ts      = data.get("ts") or ""
    payload = data.get("data") or {}

    with _hub_lock:
        if tester not in _hub_sessions:
            _hub_sessions[tester] = {
                "events": [], "last_seen": ts, "status": "running",
                "device": "", "duration_hours": None, "interval_hours": None,
            }
        session = _hub_sessions[tester]
        session["last_seen"] = ts
        session["events"].append({"ts": ts, "event": event, "data": payload})
        if len(session["events"]) > 200:
            session["events"] = session["events"][-200:]
        if event == "run_complete":
            session["status"] = "done"
        elif event == "run_failed":
            session["status"] = "failed"
        else:
            session["status"] = "running"
        if event == "run_start":
            session["duration_hours"] = payload.get("duration_hours") or session["duration_hours"]
            session["interval_hours"] = payload.get("interval_hours") or session["interval_hours"]
        if event == "device_info":
            model   = payload.get("model") or ""
            android = payload.get("android_version") or ""
            ios     = payload.get("ios_version") or ""
            udid    = payload.get("udid") or ""
            os_label = (f"iOS {ios}" if ios
                        else f"Android {android}" if android else "")
            parts   = [p for p in [model, os_label, f"({udid})" if udid else ""] if p]
            session["device"] = " · ".join(parts[:2]) + (f" {parts[2]}" if len(parts) > 2 else "")

    return jsonify({"ok": True})


@app.route("/api/hub/sessions")
def api_hub_sessions():
    with _hub_lock:
        return jsonify(dict(_hub_sessions))


# ── ZIP build & download ──────────────────────────────────────────────────────

def _build_zip_in_memory(platform: str) -> tuple[bytes, str]:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_dist.py"),
             "--out", tmp, "--platform", platform],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
        )
        prefix = "Mac" if platform == "mac" else "Windows"
        files = [f for f in Path(tmp).iterdir() if prefix in f.name and f.suffix == ".zip"]
        if not files:
            raise FileNotFoundError(f"No {platform} ZIP found")
        zpath = files[0]
        return zpath.read_bytes(), zpath.name


@app.route("/api/download/<platform>")
def api_download(platform: str):
    if platform not in ("mac", "windows"):
        return jsonify({"error": "Invalid platform. Use mac or windows"}), 400
    try:
        data, filename = _build_zip_in_memory(platform)
        return Response(
            data,
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Failures (artifact browser) ───────────────────────────────────────────────

@app.route("/failures")
def failures():
    folders = []
    if ARTIFACTS_DIR.exists():
        for d in sorted(ARTIFACTS_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            try:
                dt    = datetime.datetime.strptime(d.name, "%Y%m%d_%H%M%S")
                label = dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                label = d.name
            files = sorted(f.name for f in d.iterdir() if f.is_file())
            folders.append({"name": d.name, "label": label, "files": files})
    return render_template("failures.html", folders=folders)


@app.route("/failures/<ts>")
def failure_detail(ts):
    folder = ARTIFACTS_DIR / ts
    if not folder.is_dir():
        return "Artifact folder not found.", 404

    try:
        dt    = datetime.datetime.strptime(ts, "%Y%m%d_%H%M%S")
        label = dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        label = ts

    def _read(name):
        p = folder / name
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None

    return render_template(
        "failure_detail.html",
        ts=ts,
        label=label,
        has_screenshot=(folder / "screenshot.png").exists(),
        error_text=_read("error.txt"),
        logcat_text=_read("logcat.txt"),
        page_source_text=_read("page_source.xml"),
        meta_text=_read("meta.json"),
    )


@app.route("/artifacts/<ts>/<filename>")
def serve_artifact(ts, filename):
    folder = ARTIFACTS_DIR / ts
    if not folder.is_dir():
        return "Not found.", 404
    return send_from_directory(str(folder), filename)


@app.route("/api/screenshots")
def api_screenshots():
    screenshots_dir = ARTIFACTS_DIR / "screenshots"
    if not screenshots_dir.exists():
        return jsonify([])
    files = sorted(
        (f.name for f in screenshots_dir.iterdir() if f.is_file()),
        reverse=True,
    )
    return jsonify(files)


# ── Report (HTML download) ─────────────────────────────────────────────────────

# TC ↔ periodic-check correlation (issue #14): some regression TCs assert the
# exact same screen/state that a scheduled hourly check re-verifies for the
# rest of the run. A TC that failed once at startup but whose periodic twin
# then passes repeatedly afterward is very likely a one-off timing glitch
# rather than a real regression (e.g. TC-MAIN-004 failed once on SM-S156V
# while the next 19 hourly bt_reconnect_ecg_result checks all came back
# clean — tester report 2026-07-16, see src/regression/main_screen.py).
_TC_PERIODIC_TWIN = {
    "TC-MAIN-004": ("bt_reconnect_ecg_result", lambda d: d.get("result") == "ECG signal visible"),
    "TC-CONN-001": ("bluetooth_off",           lambda d: True),
    "TC-CONN-004": ("bluetooth_reconnected",   lambda d: True),
}
_TC_PERIODIC_MIN_PASSES = 3  # fewer later passes isn't enough to call it "probably transient"


def _build_report_html(events: list[dict]) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    device = start_ts_str = ""
    duration_h = interval_h = None
    suites: dict = {}
    injections: list = []
    bt_tests: list = []
    ap_tests: list = []
    bt_warnings: list = []
    reg_diary: list = []
    pending_symptom = None
    nat_bt: list = []          # app-observed patch<->phone BT disconnections
    crashes: list = []         # app process deaths caught by app-watch
    in_test_window = False     # inside a scheduled BT/airplane test
    study_last_pct = None      # app study % (issue #10/#11)
    study_samples: list = []   # (ts, percent) history — mid-study ETA (issue #14 follow-up)
    study_done: dict | None = None
    study_skipped = 0          # jobs skipped after study completion

    for e in events:
        ev   = e.get("event", "")
        data = e.get("data", {})
        ts   = e.get("ts", "")

        # Track scheduled-test windows so natural BT drops can be told apart
        if ev in ("bt_disconnect_start", "airplane_mode_start"):
            in_test_window = True
        elif ev in ("bt_disconnect_done", "bt_disconnect_failed", "bt_disconnect_not_supported",
                    "airplane_mode_done", "airplane_mode_failed", "airplane_mode_skipped"):
            in_test_window = False

        if ev == "bluetooth_off":
            desc = data.get("desc", "")
            if "ak_bt_status_disconnected" in desc:
                source = "app_status"
            elif "ak_bt_guidance" in desc:
                source = "app_guidance"
            elif "phone_bluetooth_off" in desc:
                source = "phone_bt_off"
            else:
                source = "unknown"
            natural = (source in ("app_status", "app_guidance")) and not in_test_window
            nat_bt.append({
                "ts": ts, "resolved_ts": "", "during_test": in_test_window,
                "elapsed": None, "resolved": False, "source": source,
                "natural": natural,
            })
        elif ev in ("bluetooth_reconnected", "bluetooth_off_resolved"):
            if nat_bt:
                nat_bt[-1]["resolved"] = True
                nat_bt[-1]["resolved_ts"] = ts
                if data.get("elapsed_sec") is not None:
                    nat_bt[-1]["elapsed"] = data.get("elapsed_sec")
        if ev == "run_start":
            start_ts_str = ts
            duration_h   = data.get("duration_hours")
            interval_h   = data.get("interval_hours")
        elif ev == "device_info":
            model   = data.get("model", "")
            android = data.get("android_version", "")
            ios     = data.get("ios_version", "")
            os_label = (f" iOS {ios}" if ios
                        else f" Android {android}" if android else "")
            device = f"{model}{os_label} ({data.get('udid','')})"
        elif ev == "regression_suite_result":
            suites[data.get("suite", "")] = {**data, "_ts": ts}
        elif ev == "inject_start":
            pending_symptom = data.get("symptom")  # for job_failed attribution
        elif ev == "inject_done":
            injections.append({"ts": ts, "symptom": data.get("symptom"), "elapsed": data.get("elapsed_sec"), "ok": True})
            pending_symptom = None
        elif ev == "job_failed":
            injections.append({"ts": ts, "symptom": data.get("symptom") or pending_symptom or "-",
                               "elapsed": None, "ok": False, "error": data.get("error", "")})
            pending_symptom = None
        elif ev == "regression_diary_saved":
            reg_diary.append({"ts": ts, "symptom": data.get("symptom", "-"), "source": data.get("source", "")})
        elif ev == "app_crashed":
            crashes.append({"ts": ts, "kind": data.get("kind", ""),
                            "evidence": data.get("evidence", ""),
                            "evidence_activity": data.get("evidence_activity", ""),
                            "relaunched": False,
                            "deferred": data.get("relaunch") == "deferred_to_job_recovery"})
        elif ev == "app_relaunched_after_crash":
            if crashes:
                crashes[-1]["relaunched"] = True
        elif ev == "bt_disconnect_done":
            bt_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": True})
        elif ev == "bt_disconnect_not_supported":
            bt_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": None, "error": "ADB BT toggle not supported on this device/OS"})
        elif ev == "bt_disconnect_failed":
            bt_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": False, "error": data.get("error", "")})
        elif ev == "airplane_mode_done":
            ap_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": True})
        elif ev == "airplane_mode_failed":
            ap_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": False, "error": data.get("error", "")})
        elif ev == "bt_not_restored":
            phase = data.get("phase", "workflow")
            bt_warnings.append({"ts": ts, "msg": f"BT not restored after {phase} — tester must manually re-enable Bluetooth"})
        elif ev == "study_progress":
            study_last_pct = data.get("percent")
            if study_last_pct is not None:
                study_samples.append((ts, study_last_pct))
        elif ev == "study_completed":
            study_done = dict(data)
            study_done["ts"] = ts
        elif ev == "job_skipped_study_ended":
            study_skipped += 1

    elapsed_str = "-"
    if start_ts_str:
        try:
            start_dt = datetime.datetime.fromisoformat(start_ts_str)
            elapsed  = datetime.datetime.now() - start_dt
            h, rem   = divmod(int(elapsed.total_seconds()), 3600)
            elapsed_str = f"{h}h {rem // 60}m"
        except Exception:
            pass

    def _t(ts): return ts.split("T")[1][:8] if "T" in ts else ts

    def _esc(v) -> str:
        """Escape app/tester/error-sourced free text before it lands in the
        f-string HTML below — Appium exceptions occasionally contain raw
        XML-ish fragments (e.g. '<hierarchy>...') that would otherwise break
        the report's layout (code review 2026-07-22). Only wrap leaf text
        values with this, never the surrounding HTML we build ourselves."""
        return _html.escape(str(v)) if v is not None else ""

    def _periodic_footnote(tc_code: str, since_ts: str) -> str:
        """issue #14: if `tc_code`'s periodic twin (see _TC_PERIODIC_TWIN)
        passed enough times after this suite ran, note it next to the
        failure — a same-screen check passing repeatedly afterward points
        to a one-off timing glitch rather than a real regression."""
        twin = _TC_PERIODIC_TWIN.get(tc_code)
        if not twin or not since_ts:
            return ""
        event_type, is_pass = twin
        passes = sum(
            1 for e in events
            if e.get("event") == event_type and e.get("ts", "") > since_ts
            and is_pass(e.get("data", {}))
        )
        if passes < _TC_PERIODIC_MIN_PASSES:
            return ""
        return (f" <span style='color:#6b7280;font-style:italic'>"
                f"— 동일 화면 검증이 이후 {passes}회 통과 (일시적 문제일 가능성)</span>")

    inj_ok    = sum(1 for i in injections if i.get("ok"))
    inj_total = len(injections)
    inj_rate  = f"{inj_ok}/{inj_total}" if inj_total else "-"
    bt_ok     = sum(1 for t in bt_tests if t["ok"] is True)
    bt_skip   = sum(1 for t in bt_tests if t["ok"] is None)
    bt_rate   = f"{bt_ok}/{len(bt_tests) - bt_skip}" if bt_tests else "-"
    if bt_skip and bt_tests:
        bt_rate += f" ({bt_skip} skipped — ADB BT not supported)"
    ap_ok     = sum(1 for t in ap_tests if t["ok"])
    ap_rate   = f"{ap_ok}/{len(ap_tests)}" if ap_tests else "-"

    # ── App Study Summary (issue #11) ────────────────────────────────────
    # The app/patch study runs on its own schedule, independent of this run.
    study_html = ""
    study_action_html = ""
    if study_done or study_last_pct is not None:
        # (label, value_html, full_width) — full_width for items whose value
        # is a long sentence rather than a short fact (tester feedback
        # 2026-07-21: plain Item/Value table looked cluttered; switched to
        # the same boxed key/value grid as the header meta info).
        items: list[tuple[str, str, bool]] = []
        if study_done:
            up = study_done.get("upload_percent")
            items.append(("Status", "<span style='color:#059669'>✓ Completed</span>", False))
            if up is not None:
                up_color = "#059669" if str(up) == "100" else "#d97706"
                items.append(("Data Upload", f"<span style='color:{up_color}'>{up}%</span>", False))
                if str(up) != "100":
                    study_action_html = f"""
    <div class="callout callout-warn">
      <div class="callout-title">⚠ ACTION REQUIRED: Data upload is at {up}%</div>
      <div class="callout-body">Tap the 'Upload' button in the app to finish uploading the study data.</div>
    </div>"""
            if study_done.get("study_start") or study_done.get("study_end"):
                # As-shown-on-phone timestamps — the phone's timezone may
                # differ from this report's (tester feedback 2026-07-21:
                # a device set to America/Chicago made the app's times look
                # ~14h off from the rest of the report, which uses this
                # server's local time). Label it so readers don't compare
                # the two ranges as if they share a timezone.
                items.append(("Study Window (device local time)",
                             f"{study_done.get('study_start','?')} ~ {study_done.get('study_end','?')}", True))
            end_s = study_done.get("study_end")
            if end_s:
                try:
                    end_dt = datetime.datetime.fromisoformat(end_s)
                    # Correct for device/host timezone mismatch (2026-07-21:
                    # a device on America/Chicago made this comparison
                    # naive-vs-naive across a 14h gap, wrongly bucketing
                    # half the injections as "after study end").
                    tz_offset = study_done.get("device_tz_offset_seconds")
                    if tz_offset is not None:
                        end_dt += datetime.timedelta(seconds=tz_offset)
                    valid = sum(1 for i in injections if i.get("ok") and i.get("ts")
                                and datetime.datetime.fromisoformat(i["ts"].split(".")[0]) <= end_dt)
                    after = inj_ok - valid
                    label = f"{valid}/{inj_ok} within the study window"
                    if after:
                        label += f" · {after} after study end (not in study data)"
                    items.append(("Injections (in study window)", label, True))
                except Exception:
                    pass
            if study_skipped:
                items.append(("Skipped Jobs", f"{study_skipped} scheduled job(s) skipped after study completion", True))
        else:
            # Study still in progress — tester feedback 2026-07-28: a report
            # pulled at 98% showed nothing but the bare percent, which read
            # as broken. Add the same linear ETA the live dashboard already
            # shows (updateProgress() in index.html) plus what's known so
            # far, so a mid-study report isn't this sparse.
            last_ts, last_pct = study_samples[-1]
            progress_val = f"{last_pct}%"
            first_distinct = next((s for s in study_samples if s[1] != last_pct), None)
            if first_distinct and last_pct < 100 and last_pct > first_distinct[1]:
                try:
                    t0 = datetime.datetime.fromisoformat(first_distinct[0])
                    t1 = datetime.datetime.fromisoformat(last_ts)
                    rate = (last_pct - first_distinct[1]) / (t1 - t0).total_seconds()  # %/sec
                    if rate > 0:
                        eta_dt = t1 + datetime.timedelta(seconds=(100 - last_pct) / rate)
                        progress_val += f" · est. ends ~{eta_dt.strftime('%m/%d %H:%M')}"
                except Exception:
                    pass
            items.append(("Progress", progress_val, False))
            items.append(("Last Read", _t(last_ts), False))
            if inj_total:
                items.append(("Injections so far", f"{inj_ok}/{inj_total}", False))
        items_html = "".join(
            f"<div class='kv-item{' full' if full else ''}'>"
            f"<div class='kv-label'>{label}</div><div class='kv-val'>{val}</div></div>"
            for label, val, full in items
        )
        study_html = f"""
  <div class="card">
    <div class="card-header">
      <span class="card-icon">🩺</span>
      <span class="card-title">App Study Summary</span>
      <span class="card-count">{'completed' if study_done else f'{study_last_pct}%'}</span>
    </div>
    <div style="font-size:.72rem;color:#9ca3af;margin-bottom:8px">The app/patch study runs on its own schedule, independent of this automation run.</div>
    <div class="kv-grid">{items_html}</div>
    {study_action_html}
  </div>"""

    total_p = sum(d.get("passed", 0) for d in suites.values() if not d.get("skipped"))
    total_t = sum(d.get("total",  0) for d in suites.values() if not d.get("skipped"))
    overall_ok = total_t > 0 and total_p == total_t
    overall_icon = "✅" if overall_ok else ("⚠️" if total_t == 0 else "❌")
    overall_label = "PASS" if overall_ok else ("N/A" if total_t == 0 else "FAIL")

    def _suite_badge(d):
        if d.get("skipped"):
            return "<span class='badge badge-skip'>SKIP</span>"
        ok = d.get("passed") == d.get("total")
        cls = "badge-pass" if ok else "badge-fail"
        n_skip = len(d.get("skipped_tests") or [])
        skip_note = (f" <span class='badge badge-skip'>{n_skip} skipped</span>" if n_skip else "")
        return f"<span class='badge {cls}'>{'✓' if ok else '✗'} {d['passed']}/{d['total']}</span>{skip_note}"

    suite_html = ""
    for name, d in suites.items():
        fails = d.get("failures", [])
        skips = d.get("skipped_tests", [])
        fail_html = ""
        if fails and not d.get("skipped") and d.get("passed") != d.get("total"):
            suite_ts = d.get("_ts", "")
            items = "".join(
                f"<li>{_esc(f[:80])}{_periodic_footnote(f.split(':', 1)[0].strip(), suite_ts)}</li>"
                for f in fails[:5])
            # Evidence filenames so the tester/QA can open the screenshot
            # without digging through the artifacts folder (issue #13)
            shots = d.get("failure_screenshots") or {}
            if shots:
                items += "".join(
                    f"<li style='color:#9ca3af;list-style:none'>evidence: {_esc(tc)} → {_esc(fn)} (screenshots folder)</li>"
                    for tc, fn in list(shots.items())[:5])
            fail_html = f"<ul class='fail-list'>{items}</ul>"
        skip_html = ""
        if skips:
            items = "".join(f"<li style='color:#d97706'>{_esc(s[:100])}</li>" for s in skips[:5])
            skip_html = f"<ul class='fail-list'>{items}</ul>"
        suite_html += f"<div class='suite-row'><span class='suite-name'>{_esc(name)}</span>{_suite_badge(d)}{fail_html}{skip_html}</div>"

    def _dur(sec):
        if sec is None:
            return "?"
        m, s = divmod(int(sec), 60)
        return f"{m}m {s}s" if m else f"{s}s"

    nat_bt_html = ""
    for n in nat_bt:
        if not n.get("natural"):
            continue
        tag = "<span class='dur' style='color:#d97706;font-weight:600'>natural patch link</span>"
        status = (f"<span class='ok'>✓ reconnected ({_dur(n['elapsed'])})</span>" if n["resolved"]
                  else "<span class='err'>✗ not reconnected</span>")
        reconnected_at = _t(n.get("resolved_ts", "")) if n.get("resolved_ts") else "-"
        nat_bt_html += (f"<div class='list-row'><span class='ts'>{_t(n['ts'])}"
                        f" <span style='color:#dc2626;font-weight:600'>- Disconnected time</span></span>"
                        f"{tag}<span class='dur'>reconnected {reconnected_at}</span>{status}</div>")
    nat_count = sum(1 for n in nat_bt if n.get("natural"))

    crash_html = ""
    for c in crashes:
        kind = {"process_gone": "crashed (process gone)",
                "silent_restart": "crashed & auto-restarted by OS"}.get(c["kind"], c["kind"])
        ev_name = os.path.basename(c["evidence"]) if c.get("evidence") else "no crash log captured"
        # ActivityManager evidence (issue: crash root cause) — separate from
        # the Java-exception crash buffer above, since OS-initiated kills
        # (low memory, frozen-state, force-stop) never appear there.
        ev_activity = (f" + {_esc(os.path.basename(c['evidence_activity']))}"
                       if c.get("evidence_activity") else "")
        if c["relaunched"]:
            state = "<span class='ok'>✓ relaunched</span>"
        elif c["kind"] == "silent_restart":
            state = "<span class='dur'>self-recovered</span>"
        elif c.get("deferred"):
            state = "<span class='dur' style='color:#d97706'>… recovery pending</span>"
        else:
            state = "<span class='err'>✗ relaunch failed</span>"
        crash_html += (f"<div class='list-row'><span class='ts'>{_t(c['ts'])}</span>"
                       f"<span class='symptom' style='color:#dc2626'>{_esc(kind)}</span>"
                       f"<span class='dur'>{_esc(ev_name)}{ev_activity}</span>{state}</div>")

    reg_diary_html = ""
    for r in reg_diary:
        reg_diary_html += (f"<div class='list-row'><span class='ts'>{_t(r['ts'])}</span>"
                           f"<span class='symptom'>{_esc(r['symptom'])}</span>"
                           f"<span class='dur'>{_esc(r['source'])}</span></div>")

    inj_html = ""
    for i in injections:
        if i.get("ok"):
            inj_html += f"<div class='list-row'><span class='ts'>{_t(i['ts'])}</span><span class='symptom'>{_esc(i.get('symptom')) or '-'}</span><span class='dur'>{i['elapsed']}s</span></div>"
        else:
            err = (i.get('error') or '')[:80]
            inj_html += f"<div class='list-row' style='opacity:.7'><span class='ts'>{_t(i['ts'])}</span><span class='symptom' style='color:#dc2626'>{_esc(i.get('symptom')) or '-'} ✗</span><span class='dur' style='color:#dc2626;font-size:11px'>{_esc(err)}</span></div>"

    bt_html = ""
    for t in bt_tests:
        if t["ok"] is True:
            icon = "✓"; cls = "ok"
        elif t["ok"] is None:
            icon = "⚠ skipped"; cls = "skip"
        else:
            icon = "✗"; cls = "err"
        bt_html += f"<div class='list-row'><span class='ts'>{_t(t['ts'])}</span><span class='dur'>{t.get('minutes') or '-'} min</span><span class='{cls}'>{icon}</span></div>"

    ap_html = ""
    for t in ap_tests:
        icon = "✓" if t["ok"] else "✗"
        cls  = "ok" if t["ok"] else "err"
        ap_html += f"<div class='list-row'><span class='ts'>{_t(t['ts'])}</span><span class='dur'>{t['minutes']} min</span><span class='{cls}'>{icon}</span></div>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>AK Test Report — {now}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#1a1d23;min-height:100vh;padding:32px 16px}}
  .page{{max-width:700px;margin:0 auto}}
  /* Header card */
  .header-card{{background:#1a1d23;border-radius:12px;padding:20px 24px;margin-bottom:16px;color:#fff}}
  .header-top{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
  .rocket{{font-size:1.4rem}}
  .header-title{{font-size:1.05rem;font-weight:700;color:#fff}}
  .header-sub{{font-size:.78rem;color:#9ca3af;margin-top:2px}}
  .meta-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-top:12px}}
  .meta-item{{background:#2a2d35;border-radius:7px;padding:8px 12px}}
  .meta-label{{font-size:.65rem;color:#6b7280;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}}
  .meta-val{{font-size:.85rem;font-weight:600;color:#e5e7eb;font-family:'SF Mono','Fira Mono',monospace}}
  /* Overall badge */
  .overall{{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;font-size:.82rem;font-weight:700;margin-top:12px}}
  .overall-pass{{background:#d1fae5;color:#065f46}}
  .overall-fail{{background:#fee2e2;color:#991b1b}}
  .overall-na{{background:#fef3c7;color:#92400e}}
  /* Section cards */
  .card{{background:#fff;border-radius:10px;padding:16px 20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
  .card-header{{display:flex;align-items:center;gap:8px;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #f3f4f6}}
  .card-icon{{font-size:1.05rem}}
  .card-title{{font-size:.88rem;font-weight:700;color:#111827}}
  .card-count{{margin-left:auto;font-size:.75rem;color:#6b7280;background:#f3f4f6;padding:2px 8px;border-radius:10px}}
  /* Key/value grid — same visual language as the header meta-grid, for light cards */
  .kv-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}
  .kv-item{{background:#f9fafb;border-radius:8px;padding:8px 12px}}
  .kv-item.full{{grid-column:1 / -1}}
  .kv-label{{font-size:.68rem;color:#9ca3af;text-transform:uppercase;letter-spacing:.4px;margin-bottom:3px}}
  .kv-val{{font-size:.83rem;font-weight:600;color:#1f2937}}
  .callout{{border-radius:8px;padding:9px 12px;margin-top:10px}}
  .callout-warn{{background:#fef3c7;border-left:3px solid #d97706}}
  .callout-title{{color:#b45309;font-weight:700;font-size:.82rem}}
  .callout-body{{color:#92400e;font-size:.8rem;margin-top:3px}}
  /* Suite rows */
  .suite-row{{display:flex;align-items:flex-start;gap:10px;padding:7px 0;border-bottom:1px solid #f9fafb;flex-wrap:wrap}}
  .suite-row:last-child{{border-bottom:none}}
  .suite-name{{font-size:.82rem;font-weight:600;color:#374151;min-width:100px;text-transform:capitalize}}
  .badge{{font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:10px}}
  .badge-pass{{background:#d1fae5;color:#065f46}}
  .badge-fail{{background:#fee2e2;color:#991b1b}}
  .badge-skip{{background:#fef3c7;color:#92400e}}
  .fail-list{{margin:4px 0 0 0;padding-left:16px;font-size:.72rem;color:#dc2626;width:100%;list-style:disc}}
  .fail-list li{{padding:1px 0}}
  /* List rows */
  .list-row{{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f9fafb;font-size:.82rem}}
  .list-row:last-child{{border-bottom:none}}
  .ts{{font-family:'SF Mono','Fira Mono',monospace;font-size:.75rem;color:#6b7280;min-width:70px}}
  .symptom{{flex:1;color:#374151}}
  .dur{{color:#6b7280;font-size:.75rem;min-width:50px;text-align:right}}
  .ok{{color:#059669;font-weight:700;min-width:24px;text-align:center}}
  .err{{color:#dc2626;font-weight:700;min-width:24px;text-align:center}}
  .empty{{font-size:.8rem;color:#9ca3af;font-style:italic;padding:4px 0}}
</style>
</head>
<body>
<div class="page">

  <div class="header-card">
    <div class="header-top">
      <span class="rocket">🩺</span>
      <div>
        <div class="header-title">S-Patch Accurkardia — Test Report</div>
        <div class="header-sub">Generated {now}</div>
      </div>
    </div>
    <div class="meta-grid">
      <div class="meta-item"><div class="meta-label">Device</div><div class="meta-val">{_esc(device) or '-'}</div></div>
      <div class="meta-item"><div class="meta-label">Elapsed</div><div class="meta-val">{elapsed_str} / {duration_h}h</div></div>
      <div class="meta-item"><div class="meta-label">Injections (all)</div><div class="meta-val">{inj_rate}</div></div>
      <div class="meta-item"><div class="meta-label">Interval</div><div class="meta-val">every {interval_h}h</div></div>
    </div>
    <div class="overall overall-{'pass' if overall_ok else ('na' if total_t==0 else 'fail')}">{overall_icon} Regression {overall_label} — {total_p}/{total_t}</div>
  </div>
{study_html}
  <div class="card">
    <div class="card-header">
      <span class="card-icon">🧪</span>
      <span class="card-title">Regression Suites</span>
      <span class="card-count">{len(suites)} suites</span>
    </div>
    {suite_html if suite_html else "<div class='empty'>No regression results yet.</div>"}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">📝</span>
      <span class="card-title">Diary Entries Created by Regression</span>
      <span class="card-count">{len(reg_diary)} entries</span>
    </div>
    <div style="font-size:.72rem;color:#9ca3af;margin-bottom:6px">These test cases save real diary entries — expect them in the portal alongside the scheduled injections below.</div>
    {reg_diary_html if reg_diary_html else "<div class='empty'>No regression-created entries (skip-regression run or older tool version).</div>"}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">💉</span>
      <span class="card-title">Symptom Injections</span>
      <span class="card-count">{inj_rate} succeeded</span>
    </div>
    {inj_html if inj_html else "<div class='empty'>No injections yet.</div>"}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">📡</span>
      <span class="card-title">BT Disconnect Tests</span>
      <span class="card-count">{bt_rate} succeeded</span>
    </div>
    {bt_html if bt_html else "<div class='empty'>No BT tests yet.</div>"}
    {"".join(f"<div class='list-row' style='background:#fef3c7;border-left:3px solid #d97706;padding:6px 10px;margin-top:4px'><span class='ts'>{_t(w['ts'])}</span><span style='color:#b45309;font-weight:600'>⚠ ACTION REQUIRED: {_esc(w['msg'])}</span></div>" for w in bt_warnings)}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">✈️</span>
      <span class="card-title">Airplane Mode Tests</span>
      <span class="card-count">{ap_rate} succeeded</span>
    </div>
    {ap_html if ap_html else "<div class='empty'>No airplane tests yet.</div>"}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">📶</span>
      <span class="card-title">Observed BT Disconnections</span>
      <span class="card-count">{nat_count} natural</span>
    </div>
    <div style="font-size:.72rem;color:#9ca3af;margin-bottom:6px">Detected by the 30s connectivity monitor. Shows only unscheduled S-Patch Bluetooth link drops reported by the app; scheduled BT signal and airplane-mode test drops are excluded.</div>
    {nat_bt_html if nat_bt_html else "<div class='empty'>No unscheduled BT disconnections observed.</div>"}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">💥</span>
      <span class="card-title">App Crashes</span>
      <span class="card-count" {'style="background:#fee2e2;color:#991b1b;font-weight:700"' if crashes else ''}>{len(crashes)} detected</span>
    </div>
    <div style="font-size:.72rem;color:#9ca3af;margin-bottom:6px">App process deaths caught by the 30s app-watch (ADB pidof). Crash-buffer logcat is saved as evidence for the app team — see the artifacts folder.</div>
    {crash_html if crash_html else "<div class='empty'>No app crashes detected.</div>"}
  </div>

</div>
</body></html>"""


@app.route("/api/report")
def api_report():
    with _lock:
        out_dir = _state["out_dir"]
    if not out_dir:
        # Server restart clears in-memory state even for a run that already
        # finished — fall back to the most recent output dir so the report
        # for a just-completed run doesn't come back empty (code review
        # 2026-07-22; same fallback /api/status already uses).
        out_dir = _find_latest_output_dir()
    events = read_events(out_dir) if out_dir else []
    html   = _build_report_html(events)
    ts     = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        html,
        mimetype="text/html",
        headers={"Content-Disposition": f"inline; filename=ak_report_{ts}.html"},
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"
    if not os.environ.get("AK_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"\n  S-Patch Accurkardia Test UI   -> http://localhost:{PORT}")
    print(f"  Share on local network        -> http://{local_ip}:{PORT}\n")
    # Main thread only — signal.signal requires it, and Flask's threaded
    # request handling below means api_start() itself can no longer be
    # the one to call this (see _register_exit_hooks docstring).
    _register_exit_hooks()
    # Only start the auto-open-report watcher once the server is actually
    # running — not on plain `import web.app` (a test/script importing this
    # module and touching _state["out_dir"] would otherwise risk a real
    # browser popping open if AK_NO_BROWSER isn't set; review 2026-07-29).
    threading.Thread(target=_auto_open_loop, daemon=True).start()
    app.run(host="::", port=PORT, debug=False, threaded=True)
