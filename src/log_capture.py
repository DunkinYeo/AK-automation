"""
Automates AccurKardia's hidden app-log export flow and pulls the resulting
zip to a local directory via adb.

Flow, confirmed live on a real device (Pixel 7, Android 16, release build,
2026-08-11): Setting menu -> Version Information -> tap the app icon 10x
(undocumented easter egg, reveals a file browser beneath the version
display) -> tap the most recent file row -> Download. The app writes the
export to /sdcard/Download/<uuid>.zip -- plain external storage, no
run-as/debuggable build needed. (The app's internal-only storage IS
blocked on this release build -- confirmed separately; that's why the
flow specifically uses the Download button, not raw adb pull of app data.)
See issue #55.
"""
import re
import subprocess
import time
from pathlib import Path

from src.regression.helpers import open_menu

_UUID_RE = re.compile(
    r'text="([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'
)

# Any of these being visible means open_menu() can reach the gear/hamburger
# icon from here (Step 1 and the main measurement screen both expose it in
# the same spot) -- used by _ensure_menu_reachable() to know when to stop
# backing out of whatever screen the app happened to be on when capture was
# requested.
_MENU_REACHABLE_SCREENS = [
    "Connect Your S-Patch", "Log Symptoms", "My Study Progress",
    "Device Status", "Start Study", "Setting", "Version Information",
]

# Subset used when returning the device to its normal resting screen
# after a capture finishes -- Setting/Version Information are deliberately
# excluded here even though they're valid open_menu() entry points.
# Real report, 2026-08-19: capture always ends with the app still sitting
# inside Settings (that's where the file browser/Download flow lives), so
# calling _ensure_menu_reachable() with the broad list above in the
# post-capture cleanup trivially "succeeds" the instant it's called --
# Version Information is itself in that list -- and strands the app deep
# in Settings instead of back on the actual main/Step-1 screen a tester
# or the next job expects.
_MAIN_SCREENS = [
    "Connect Your S-Patch", "Log Symptoms", "My Study Progress",
    "Device Status", "Start Study",
]


class LogCaptureError(Exception):
    pass


def _adb_run_with_retry(cmd, **kwargs):
    """Run an adb subprocess command, retrying once via a full daemon
    restart if it fails. Real incident, 2026-08-20: another Mac app
    (Chrome's chrome://inspect USB device inspector, even a ChatGPT
    desktop app) briefly grabbing exclusive USB access to the same
    device caused genuine kernel-level pipe stalls that failed a bare
    `adb pull` outright (0 bytes transferred). Can't prevent the
    conflict itself -- host-side, outside this tool's control -- but
    it's reliably transient: `adb kill-server && adb start-server`
    clears it every time (same fix already used in driver.py's
    wait_for_adb_device(), issue #62)."""
    result = subprocess.run(cmd, **kwargs)
    if result.returncode == 0:
        return result
    try:
        subprocess.run(["adb", "kill-server"], capture_output=True, timeout=10)
        time.sleep(1)
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=10)
        time.sleep(1)
    except Exception:
        pass
    return subprocess.run(cmd, **kwargs)


def _ensure_menu_reachable(drv, max_back_presses: int = 6, target_screens=None) -> None:
    """
    Best-effort recovery to a screen where open_menu() is known to work,
    regardless of what screen the app was on when capture was requested
    (a real tester will click "Capture App Logs" from wherever they
    noticed a problem, not just from Step 1 -- issue #55 follow-up,
    2026-08-11). Uses Back presses only, never a hard app restart: a
    restart would drop the BLE connection to a live S-Patch mid-study,
    which is unacceptable when this runs during an active regression run.

    target_screens overrides which screens count as "reached" -- defaults
    to _MENU_REACHABLE_SCREENS (includes Setting/Version Information, for
    the pre-capture call that just needs open_menu() to work from here).
    Pass _MAIN_SCREENS for the post-capture cleanup so it keeps backing
    out past Settings instead of stopping the instant it's called.
    """
    target_screens = target_screens if target_screens is not None else _MENU_REACHABLE_SCREENS
    try:
        pkg = drv.cfg.get("app_package")
        if pkg:
            drv.drv.activate_app(pkg)
            time.sleep(1.0)
    except Exception:
        pass

    for _ in range(max_back_presses):
        if drv.is_visible_text(target_screens, timeout=1):
            return
        # A handful of popups can block Back navigation entirely (same set
        # go_to_main() already knows about) -- dismiss them if present.
        for popup_text, btn in [("Cannot find your S-Patch", ["Ok", "OK"]),
                                 ("Reset your S-Patch",       ["Ok", "OK"]),
                                 ("Bluetooth not enabled",    ["Ok", "OK"]),
                                 ("No Study Information",     ["Confirm", "Ok", "OK"]),
                                 ("No study information",     ["Confirm", "Ok", "OK"])]:
            if drv.is_visible_text(popup_text, timeout=1):
                try:
                    drv.tap_text(btn, timeout=3, contains=False)
                    time.sleep(0.5)
                except Exception:
                    pass
                break
        else:
            try:
                drv.drv.press_keycode(4)  # Back
            except Exception:
                pass
            time.sleep(0.8)
    # Not finding a known screen after max_back_presses isn't fatal here --
    # open_menu() makes its own 3 attempts (including coordinate fallbacks)
    # and raises a clear, diagnosable error if it truly can't find the icon.


def capture_app_logs(drv, out_dir: Path, timeout: int = 180) -> Path:
    """
    Returns the local path to the pulled zip. Raises LogCaptureError on
    any failure; a diagnostic screenshot is saved via drv.screenshot()
    before raising. Safe to call from any screen the app happens to be on.

    Always attempts to leave the app back on a known-reachable screen
    before returning, success or failure — a real run sat on the Folder
    Information modal (Download/Share still showing) for 14+ minutes
    after a successful capture with zero automation activity in between
    (2026-08-12), because nothing navigated back afterward and the next
    scheduled job's own recovery apparently couldn't get out of it either.
    """
    try:
        return _capture_app_logs_inner(drv, out_dir, timeout)
    finally:
        # Real incident, 2026-08-20: this cleanup call itself can land in
        # the same transient USB/adb disruption window that just made the
        # inner capture fail (another app briefly grabbing exclusive USB
        # access -- kernel-level pipe stalls, ~1-2s), silently failing too
        # (bare except below) and leaving the app stranded exactly where
        # it was -- confirmed live, found sitting on the Folder
        # Information / File Information screen (with an "End Study"
        # button one screen away) for the rest of the run. One retry with
        # a short delay costs almost nothing and meaningfully raises the
        # odds of landing outside that window.
        for attempt in range(2):
            try:
                _ensure_menu_reachable(drv, target_screens=_MAIN_SCREENS)
                break
            except Exception:
                if attempt == 0:
                    time.sleep(2)


def _capture_app_logs_inner(drv, out_dir: Path, timeout: int) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        _ensure_menu_reachable(drv)
        open_menu(drv)
        drv.tap_text("Version Information", timeout=10)
        time.sleep(1.5)
    except Exception as e:
        drv.screenshot("capture_logs_menu_nav_failed")
        raise LogCaptureError(f"Could not reach Version Information screen: {e}")

    # Undocumented easter egg: tapping the app icon 10x unlocks the file
    # browser beneath the version display. A hardcoded fraction of
    # get_window_size() (0.5, 0.4904) worked on a Pixel 7 (1080x2400,
    # gesture nav) but MISSED the icon on a Samsung SM-A325N at the same
    # physical 1080x2400 -- get_window_size() reports the full physical
    # screen on both, but the 3-button nav bar eats real content height on
    # the Samsung, so the same fraction lands in a different spot relative
    # to the actual layout (confirmed live, 2026-08-11). Anchoring off the
    # "Current Version" text element instead is resolution/chrome-
    # independent: the icon sits a fixed offset above it on both devices
    # (measured delta: -220px Pixel 7, -222.5px Samsung -- consistent).
    try:
        version_el = drv.find("Current Version", timeout=10, contains=True)
        loc, sz = version_el.location, version_el.size
        icon_x = loc["x"] + sz["width"] // 2
        icon_y = loc["y"] + sz["height"] // 2 - 221
    except Exception as e:
        drv.screenshot("capture_logs_no_version_anchor")
        raise LogCaptureError(f"Could not locate 'Current Version' text to anchor the icon tap: {e}")

    for _ in range(10):
        drv.drv.tap([(icon_x, icon_y)])
        time.sleep(0.3)
    time.sleep(1.5)

    src = drv.drv.page_source
    if "File Information" not in src or "Current Version" in src:
        # Still showing the pre-unlock version screen (or navigated
        # somewhere unrelated) -- the easter egg tap sequence didn't land.
        # Note: a *successfully* unlocked file browser with zero exported
        # sessions ever recorded on this device is a normal, valid state
        # (no "Current Version" text, no UUID rows) -- not treated as
        # failure here, only actually failing to leave the version screen is.
        drv.screenshot("capture_logs_easter_egg_failed")
        raise LogCaptureError(
            "Easter egg tap sequence didn't unlock the file browser -- "
            "icon position may have changed in a newer app version"
        )

    m = _UUID_RE.search(src)
    if not m:
        drv.screenshot("capture_logs_empty_file_list")
        raise LogCaptureError(
            "File browser unlocked but has no exported sessions to capture "
            "(this device/app install has no log-export history yet)"
        )
    file_id = m.group(1)

    zip_name = f"{file_id}.zip"
    remote_path = f"/sdcard/Download/{zip_name}"
    local_path = out_dir / zip_name

    # Every capture of the same study/session re-exports to this SAME
    # UUID filename (confirmed live, 2026-08-12: two captures of the same
    # run 4.5h apart both produced .../<same-uuid>.zip) -- if a stale copy
    # from an earlier capture is still sitting at remote_path when
    # _wait_for_stable_file starts polling, its already-stable size can
    # pass the two-consecutive-checks test before the new export has even
    # started writing, silently pulling stale data instead of the fresh
    # capture. Best-effort delete first so the stability check can only
    # ever observe the new file.
    _adb_run_with_retry(drv._adb_cmd() + ["shell", "rm", "-f", remote_path],
                         capture_output=True, text=True, timeout=10)

    try:
        drv.tap_text(file_id, timeout=10)
        time.sleep(1.5)
        drv.tap_text("Download", timeout=10)
    except Exception as e:
        drv.screenshot("capture_logs_download_tap_failed")
        raise LogCaptureError(f"Could not tap Download for {file_id}: {e}")

    _wait_for_stable_file(drv, remote_path, timeout=timeout)

    result = _adb_run_with_retry(
        drv._adb_cmd() + ["pull", remote_path, str(local_path)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not local_path.exists():
        raise LogCaptureError(f"adb pull failed: {result.stderr.strip()}")

    return local_path


def _wait_for_stable_file(drv, remote_path: str, timeout: int) -> None:
    """
    Poll until remote_path exists and its size is unchanged across two
    consecutive checks -- there's no explicit "download complete" signal
    available from adb, so a size-stability check is the reliable proxy
    (a lone existence check can catch the file mid-write on a large export).
    """
    deadline = time.time() + timeout
    last_size = -1
    stable_checks = 0
    while time.time() < deadline:
        result = subprocess.run(
            drv._adb_cmd() + ["shell", "stat", "-c", "%s", remote_path],
            capture_output=True, text=True, timeout=10,
        )
        out = result.stdout.strip()
        if out.isdigit():
            size = int(out)
            if size == last_size and size > 0:
                stable_checks += 1
                if stable_checks >= 2:
                    return
            else:
                stable_checks = 0
            last_size = size
        time.sleep(2)
    raise LogCaptureError(f"Timed out waiting for {remote_path} to appear/stabilize")
