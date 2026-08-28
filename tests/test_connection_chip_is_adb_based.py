"""
Regression tests for the "Connection" dashboard chip now tracking ADB
reachability instead of duplicating the "BT Signal" chip.

User-caught redundancy (2026-08-28, applies identically to MA):
connection_lost used to be set to the exact same boolean as
bluetooth_off (both derived from the same on-screen disconnect signal),
so the two chips always showed the same state -- and neither one would
have caught this session's real, repeated USB/adb-drop incidents
(found on the MA sibling project, same architecture here), since those
have nothing to do with the S-Patch's own BT link. connection_lost is
now driven by an actual `adb devices` reachability check for this
device's serial, independent of BT state.

Run: .venv/bin/pytest tests/test_connection_chip_is_adb_based.py -v
"""
import src.driver as driver_mod


class _FakeReporter:
    def __init__(self):
        self.events = []

    def log_event(self, name, data):
        self.events.append((name, data))


def _make_driver(monkeypatch, adb_devices_stdout, udid="RF9Y800127R", visible_texts=None):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": udid}
    drv.sel = {"symptom_add_text": "Log Symptoms"}
    drv.reporter = _FakeReporter()
    visible_texts = visible_texts or set()
    drv.is_visible_text = lambda t, contains=True, timeout=1: (
        any(v in t for v in visible_texts) if contains else t in visible_texts
    )
    drv.dismiss_unexpected_popups = lambda: False
    drv._adb_bt_off = lambda: False
    drv._adb_wifi_off = lambda: False
    drv.screenshot = lambda name: None

    def _fake_run(cmd, **kwargs):
        class _R:
            stdout = adb_devices_stdout
        return _R()
    monkeypatch.setattr(driver_mod.subprocess, "run", _fake_run)
    return drv


def test_adb_device_reachable_true_when_listed_as_device(monkeypatch):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "RF9Y800127R"}

    def _fake_run(cmd, **kwargs):
        class _R:
            stdout = "List of devices attached\nRF9Y800127R\tdevice\n"
        return _R()
    monkeypatch.setattr(driver_mod.subprocess, "run", _fake_run)

    assert drv._adb_device_reachable() is True


def test_adb_device_reachable_false_when_missing_entirely(monkeypatch):
    """The exact real incident found on the MA sibling project: the
    device simply doesn't show up in `adb devices` output at all."""
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "RF9Y800127R"}

    def _fake_run(cmd, **kwargs):
        class _R:
            stdout = "List of devices attached\nOTHERDEVICE\tdevice\n"
        return _R()
    monkeypatch.setattr(driver_mod.subprocess, "run", _fake_run)

    assert drv._adb_device_reachable() is False


def test_adb_device_reachable_false_when_unauthorized(monkeypatch):
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "RF9Y800127R"}

    def _fake_run(cmd, **kwargs):
        class _R:
            stdout = "List of devices attached\nRF9Y800127R\tunauthorized\n"
        return _R()
    monkeypatch.setattr(driver_mod.subprocess, "run", _fake_run)

    assert drv._adb_device_reachable() is False


def test_adb_device_reachable_false_on_adb_command_failure(monkeypatch):
    """Negative control for the "false negative allowed" convention used
    elsewhere in this file (_adb_bt_off/_adb_wifi_off): here, a failed
    adb call must NOT be treated as "assume connected" -- it IS the
    symptom this check exists to catch."""
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "RF9Y800127R"}

    def _raise(cmd, **kwargs):
        raise RuntimeError("adb not found")
    monkeypatch.setattr(driver_mod.subprocess, "run", _raise)

    assert drv._adb_device_reachable() is False


def test_adb_device_reachable_true_when_no_udid_configured():
    """Nothing to check against — must not false-alarm."""
    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {}
    assert drv._adb_device_reachable() is True


def test_adb_device_reachable_true_when_cfg_attribute_missing_entirely():
    """Real regression caught live (2026-08-28): test_battery_status_labels.py
    builds a driver stub via object.__new__() and never sets .cfg at all,
    since it doesn't exercise anything udid-related -- check_connectivity()
    still calls this method unconditionally. Must degrade the same way
    "no udid configured" does, not raise AttributeError."""
    drv = object.__new__(driver_mod.AndroidDriver)
    assert not hasattr(drv, "cfg")
    assert drv._adb_device_reachable() is True


def test_connection_lost_fires_when_adb_unreachable_even_though_bt_is_fine(monkeypatch):
    """The core behavior change: BT/S-Patch is fully connected (main
    screen visible, no disconnect text), but adb can't see the device --
    connection_lost must fire anyway. Under the old logic (connection_lost
    == bt_disconnected) this would have stayed False."""
    drv = _make_driver(
        monkeypatch,
        adb_devices_stdout="List of devices attached\n",  # device not listed
        visible_texts={"Log Symptoms"},  # on main screen, BT looks fine
    )

    drv.check_connectivity()

    assert ("connection_lost", {"desc": "ADB connection lost"}) in drv.reporter.events


def test_connection_lost_does_not_fire_when_adb_reachable_even_though_bt_is_down(monkeypatch):
    """Negative control / the redundancy this whole change fixes: BT is
    down (Bluetooth Disconnected card showing) but the phone is still
    fully reachable over adb -- connection_lost must NOT fire, since
    that's now a distinct signal from bluetooth_off."""
    drv = _make_driver(
        monkeypatch,
        adb_devices_stdout="List of devices attached\nRF9Y800127R\tdevice\n",
        visible_texts={"Log Symptoms", "Bluetooth", "Disconnected"},
    )

    drv.check_connectivity()

    logged_names = [n for n, _ in drv.reporter.events]
    assert "connection_lost" not in logged_names
    assert any(n == "bluetooth_off" for n in logged_names)
