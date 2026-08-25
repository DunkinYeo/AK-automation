"""
Regression tests for a real bug found 2026-08-25: _read_wifi_cache()
(src/driver.py) read only the top-level device_id/wifi_ip/tcp_port
fields of runtime/adb_wifi_device.json, ignoring the "devices" list and
never checking whether those fields even belonged to the current run's
udid. The top-level fields hold whichever device most recently ran
/api/detect-wifi -- a USB-only device that has never used WiFi ADB at
all still got a wasted ~10s `adb connect` attempt to a completely
unrelated device's cached address on every single reconnect.

Run: .venv/bin/pytest tests/test_wifi_cache_udid_match.py -v
"""
import json

import src.driver as driver_mod


def _write_cache(tmp_path, data):
    p = tmp_path / "adb_wifi_device.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return (p,)


def test_matches_udid_in_devices_list():
    cache_data = {
        "device_id": "PIXELSERIAL", "wifi_ip": "192.168.0.41", "tcp_port": 5555,
        "devices": [
            {"device_id": "PIXELSERIAL", "wifi_ip": "192.168.0.41", "tcp_port": 5555},
            {"device_id": "SAMSUNGSERIAL", "wifi_ip": "192.168.0.99", "tcp_port": 5555},
        ],
    }
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        paths = _write_cache(Path(d), cache_data)
        result = driver_mod._read_wifi_cache("SAMSUNGSERIAL", _cache_paths=paths)

    assert result == "192.168.0.99:5555"


def test_does_not_return_unrelated_top_level_address_for_unknown_udid():
    """The exact real bug: a USB-only device never in the cache at all
    must get None (no wasted adb connect attempt), not the top-level
    entry belonging to a completely different device."""
    cache_data = {
        "device_id": "PIXELSERIAL", "wifi_ip": "192.168.0.41", "tcp_port": 5555,
        "devices": [
            {"device_id": "PIXELSERIAL", "wifi_ip": "192.168.0.41", "tcp_port": 5555},
        ],
    }
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        paths = _write_cache(Path(d), cache_data)
        result = driver_mod._read_wifi_cache("SM_A165N_USB_SERIAL", _cache_paths=paths)

    assert result is None


def test_falls_back_to_top_level_for_legacy_cache_without_devices_list():
    """Cache files written before the "devices" list existed only have
    the top-level fields -- must still work for that one device."""
    cache_data = {"device_id": "PIXELSERIAL", "wifi_ip": "192.168.0.41", "tcp_port": 5555}
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        paths = _write_cache(Path(d), cache_data)
        result = driver_mod._read_wifi_cache("PIXELSERIAL", _cache_paths=paths)

    assert result == "192.168.0.41:5555"


def test_no_cache_file_returns_none():
    from pathlib import Path
    result = driver_mod._read_wifi_cache("ANY", _cache_paths=(Path("/nonexistent/adb_wifi_device.json"),))
    assert result is None


def test_ensure_adb_connected_skips_adb_call_entirely_when_udid_not_cached(monkeypatch):
    """Integration point: _ensure_adb_connected() must not attempt any
    adb connect at all for a USB-only device that isn't in the cache --
    previously this always fired a wasted ~10s attempt to whatever
    device's address happened to be cached."""
    calls = []
    monkeypatch.setattr(driver_mod.subprocess, "run",
                         lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("must not call adb")))
    monkeypatch.setattr(driver_mod, "_read_wifi_cache", lambda udid: None)

    drv = object.__new__(driver_mod.AndroidDriver)
    drv.cfg = {"udid": "SM_A165N_USB_SERIAL"}
    drv.reporter = type("R", (), {"log_event": staticmethod(lambda *a, **k: None)})()
    drv._last_adb_reconnect_at = 0.0

    drv._ensure_adb_connected()

    assert calls == []
