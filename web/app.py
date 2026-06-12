"""
S-Patch Accurkardia Long-run Test — Web UI backend
Run:  python web/app.py   (from project root)
"""
import atexit
import datetime
import json
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request, send_from_directory, Response

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ARTIFACTS_DIR = ROOT / "artifacts"

app = Flask(__name__)

PORT = 5003

# ── Shared state ─────────────────────────────────────────────────────────────
_state: dict = {"proc": None, "out_dir": None, "start_ts": None}
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


def appium_ok() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:4723/status", timeout=2) as r:
            return json.loads(r.read()).get("value", {}).get("ready", False)
    except Exception:
        return False


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
                events.append(json.loads(line))
            except Exception:
                pass
    return events


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
                    udid    = data.get("udid", "")
                    ver     = f" · Android {android}" if android else ""
                    device  = f"{model}{ver} ({udid})" if model else udid
                elif ev == "run_start":
                    duration_hours = duration_hours or data.get("duration_hours")
                    interval_hours = interval_hours or data.get("interval_hours")
                last_ts = e.get("ts", last_ts)

            names = {e["event"] for e in events}
            status = "done" if "run_complete" in names else "failed" if "run_failed" in names else "running"

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
    import shutil
    while True:
        time.sleep(30)
        try:
            with _lock:
                proc = _state.get("proc")
                running = bool(proc and proc.poll() is None)
            if not running:
                continue
            if appium_ok():
                continue
            appium_cmd = _find_appium_cmd()
            if not appium_cmd:
                continue
            log.warning("[watchdog] Appium down — restarting...")
            subprocess.Popen(
                [appium_cmd, "--port", "4723"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(3)
            if appium_ok():
                log.info("[watchdog] Appium restarted successfully")
            else:
                log.warning("[watchdog] Appium restart failed")
        except Exception:
            pass


threading.Thread(target=_appium_watchdog, daemon=True).start()


def _kill_proc():
    with _lock:
        proc = _state.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

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
    return jsonify({"devices": get_devices(), "appium": appium_ok(), "cached_wifi": get_cached_wifi()})


@app.route("/api/detect-wifi", methods=["POST"])
def api_detect_wifi():
    """Detect WiFi IP from first USB-connected ADB device, save cache, return address."""
    devices = get_devices()
    usb_serial = next((d for d in devices if ":" not in d), None)
    if not usb_serial:
        return jsonify({"error": "No USB device connected"}), 400
    try:
        r = subprocess.run(
            ["adb", "-s", usb_serial, "shell", "ip", "route"],
            capture_output=True, text=True, timeout=10,
        )
        import re
        m = re.search(r"src (\d+\.\d+\.\d+\.\d+)", r.stdout)
        if not m:
            return jsonify({"error": "Could not determine WiFi IP from device"}), 400
        wifi_ip = m.group(1)
        subprocess.run(["adb", "-s", usb_serial, "tcpip", "5555"], capture_output=True, timeout=10)
        time.sleep(1)
        subprocess.run(["adb", "connect", f"{wifi_ip}:5555"], capture_output=True, timeout=10)
        cache = ROOT / "runtime" / "adb_wifi_device.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({
            "device_id": usb_serial,
            "wifi_ip": wifi_ip,
            "tcp_port": 5555,
            "updated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }))
        return jsonify({"wifi_addr": f"{wifi_ip}:5555"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

        if not out_dir and start_ts:
            found = find_latest_output_dir(start_ts)
            if found:
                _state["out_dir"] = found
                out_dir = found

        events    = read_events(out_dir)
        # If test process isn't tracked but events exist and look active, treat as running
        if not running and events and (proc or start_ts):
            last_ev = events[-1].get("event", "")
            if last_ev not in ("run_complete", "run_failed"):
                running = True
        exit_code = proc.poll() if proc else None

        return jsonify({
            "running":   running,
            "exit_code": exit_code,
            "events":    events,
        })


@app.route("/api/start", methods=["POST"])
def api_start():
    with _lock:
        if _state["proc"] and _state["proc"].poll() is None:
            return jsonify({"error": "Already running."}), 400

        data    = request.json or {}
        device  = data.get("device", "")
        serial  = data.get("serial", "").strip()

        # Optional WiFi ADB connect
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

        symptoms = data.get("symptoms") or AK_SYMPTOMS[:3]
        slack_webhook = (data.get("slack_webhook") or "").strip()

        cfg = {
            "platform": "android",
            "run": {
                "name":                          data.get("run_name") or "ak_run",
                "duration_hours":                int(data.get("duration_hours", 72)),
                "symptom_interval_hours":        float(data.get("interval_hours", 1)),
                "start_immediately":             True,
                "jitter_seconds":                0,
                "quiet_hours":                   {"start": 2, "end": 6},
                "bt_disconnect_interval_hours":  float(data.get("bt_disconnect_interval_hours", 1)),
                "bt_disconnect_minutes":         float(data.get("bt_disconnect_minutes", 10)),
                "airplane_mode_interval_hours":  float(data.get("airplane_mode_interval_hours", 1)),
                "airplane_mode_minutes":         float(data.get("airplane_mode_minutes", 5)),
            },
            "recovery": {"cooldown_seconds_between_steps": 30},
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
            "selectors":      {"android": AK_SELECTORS},
            "symptom_catalog": {"symptoms": symptoms},
            "slack": {
                "enabled":     bool(slack_webhook),
                "webhook_url": slack_webhook,
                "mention":     (data.get("slack_mention") or "").strip(),
            },
        }

        cfg_path = ROOT / "config" / "_web_run.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

        start_ts = time.time()
        _state["start_ts"] = start_ts
        _state["out_dir"]  = None
        cmd = [sys.executable, str(ROOT / "src" / "main.py"), "--config", str(cfg_path)]
        if data.get("skip_regression"):
            cmd.append("--skip-regression")
        _state["proc"]     = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
        )

        return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with _lock:
        proc = _state["proc"]
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        _state["proc"]     = None
        _state["start_ts"] = None
        _state["out_dir"]  = None
    return jsonify({"ok": True})


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
            udid    = payload.get("udid") or ""
            parts   = [p for p in [model, f"Android {android}" if android else "", f"({udid})" if udid else ""] if p]
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

def _build_report_html(events: list[dict]) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    device = start_ts_str = ""
    duration_h = interval_h = None
    suites: dict = {}
    injections: list = []
    bt_tests: list = []
    ap_tests: list = []

    for e in events:
        ev   = e.get("event", "")
        data = e.get("data", {})
        ts   = e.get("ts", "")
        if ev == "run_start":
            start_ts_str = ts
            duration_h   = data.get("duration_hours")
            interval_h   = data.get("interval_hours")
        elif ev == "device_info":
            device = f"{data.get('model','')} Android {data.get('android_version','')} ({data.get('udid','')})"
        elif ev == "regression_suite_result":
            suites[data.get("suite", "")] = data
        elif ev == "inject_done":
            injections.append({"ts": ts, "symptom": data.get("symptom"), "elapsed": data.get("elapsed_sec")})
        elif ev == "bt_disconnect_done":
            bt_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": True})
        elif ev == "bt_disconnect_failed":
            bt_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": False, "error": data.get("error", "")})
        elif ev == "airplane_mode_done":
            ap_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": True})
        elif ev == "airplane_mode_failed":
            ap_tests.append({"ts": ts, "minutes": data.get("minutes"), "ok": False, "error": data.get("error", "")})

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

    def _table(headers, rows, empty="No data yet."):
        if not rows:
            return f"<p style='color:#9ca3af;font-style:italic'>{empty}</p>"
        ths = "".join(f"<th>{h}</th>" for h in headers)
        trs = "".join(f"<tr>{''.join(f'<td>{c}</td>' for c in row)}</tr>" for row in rows)
        return f"<table>{ths}{trs}</table>"

    suite_rows = []
    for name, d in suites.items():
        if d.get("skipped"):
            status = "<span style='color:#d97706'>SKIP</span>"
        elif d.get("passed") == d.get("total"):
            status = f"<span style='color:#059669'>✓ {d['passed']}/{d['total']}</span>"
        else:
            fails_txt = "<br><small>" + "  ".join(d.get("failures", [])[:3]) + "</small>"
            status = f"<span style='color:#dc2626'>✗ {d['passed']}/{d['total']}{fails_txt}</span>"
        suite_rows.append([name, status])

    inj_rows = [[_t(i["ts"]), i["symptom"] or "-", f"{i['elapsed']}s"] for i in injections]
    bt_rows  = [[_t(t["ts"]), f"{t['minutes']} min",
                 "<span style='color:#059669'>✓</span>" if t["ok"] else f"<span style='color:#dc2626'>✗ {t.get('error','')}</span>"]
                for t in bt_tests]
    ap_rows  = [[_t(t["ts"]), f"{t['minutes']} min",
                 "<span style='color:#059669'>✓</span>" if t["ok"] else f"<span style='color:#dc2626'>✗ {t.get('error','')}</span>"]
                for t in ap_tests]

    total_p = sum(d.get("passed", 0) for d in suites.values() if not d.get("skipped"))
    total_t = sum(d.get("total",  0) for d in suites.values() if not d.get("skipped"))
    overall_ok = total_t > 0 and total_p == total_t
    overall_icon = "✅" if overall_ok else ("⚠️" if total_t == 0 else "❌")
    overall_label = "PASS" if overall_ok else ("N/A" if total_t == 0 else "FAIL")
    overall_color = "#059669" if overall_ok else ("#d97706" if total_t == 0 else "#dc2626")

    def _suite_badge(d):
        if d.get("skipped"):
            return "<span class='badge badge-skip'>SKIP</span>"
        ok = d.get("passed") == d.get("total")
        cls = "badge-pass" if ok else "badge-fail"
        return f"<span class='badge {cls}'>{'✓' if ok else '✗'} {d['passed']}/{d['total']}</span>"

    suite_html = ""
    for name, d in suites.items():
        fails = d.get("failures", [])
        fail_html = ""
        if fails and not d.get("skipped") and d.get("passed") != d.get("total"):
            items = "".join(f"<li>{f[:80]}</li>" for f in fails[:5])
            fail_html = f"<ul class='fail-list'>{items}</ul>"
        suite_html += f"<div class='suite-row'><span class='suite-name'>{name}</span>{_suite_badge(d)}{fail_html}</div>"

    inj_html = ""
    for i in injections:
        inj_html += f"<div class='list-row'><span class='ts'>{_t(i['ts'])}</span><span class='symptom'>{i['symptom'] or '-'}</span><span class='dur'>{i['elapsed']}s</span></div>"

    bt_html = ""
    for t in bt_tests:
        icon = "✓" if t["ok"] else "✗"
        cls  = "ok" if t["ok"] else "err"
        bt_html += f"<div class='list-row'><span class='ts'>{_t(t['ts'])}</span><span class='dur'>{t['minutes']} min</span><span class='{cls}'>{icon}</span></div>"

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
      <div class="meta-item"><div class="meta-label">Device</div><div class="meta-val">{device or '-'}</div></div>
      <div class="meta-item"><div class="meta-label">Elapsed</div><div class="meta-val">{elapsed_str} / {duration_h}h</div></div>
      <div class="meta-item"><div class="meta-label">Injections</div><div class="meta-val">{len(injections)}</div></div>
      <div class="meta-item"><div class="meta-label">Interval</div><div class="meta-val">every {interval_h}h</div></div>
    </div>
    <div class="overall overall-{'pass' if overall_ok else ('na' if total_t==0 else 'fail')}">{overall_icon} Regression {overall_label} — {total_p}/{total_t}</div>
  </div>

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
      <span class="card-icon">💉</span>
      <span class="card-title">Symptom Injections</span>
      <span class="card-count">{len(injections)} total</span>
    </div>
    {inj_html if inj_html else "<div class='empty'>No injections yet.</div>"}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">📡</span>
      <span class="card-title">BT Disconnect Tests</span>
      <span class="card-count">{len(bt_tests)} total</span>
    </div>
    {bt_html if bt_html else "<div class='empty'>No BT tests yet.</div>"}
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">✈️</span>
      <span class="card-title">Airplane Mode Tests</span>
      <span class="card-count">{len(ap_tests)} total</span>
    </div>
    {ap_html if ap_html else "<div class='empty'>No airplane tests yet.</div>"}
  </div>

</div>
</body></html>"""


@app.route("/api/report")
def api_report():
    with _lock:
        out_dir = _state["out_dir"]
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
    import webbrowser
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"\n  S-Patch Accurkardia Test UI   -> http://localhost:{PORT}")
    print(f"  Share on local network        -> http://{local_ip}:{PORT}\n")
    app.run(host="::", port=PORT, debug=False, threaded=True)
