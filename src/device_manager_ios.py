"""
DeviceManagerIOS — wraps a single IOSDriver.
Same interface as DeviceManager so callers are interchangeable.

NEW FILE — does not modify src/device_manager.py (Android) in any way.
"""
from src.driver_ios import IOSDriver


class DeviceManagerIOS:
    def __init__(self, device_cfg: dict, selectors: dict, artifacts, reporter):
        self._udid = device_cfg.get("udid", "ios-device")
        self._driver = IOSDriver(device_cfg, selectors, artifacts, reporter)

    @property
    def driver(self) -> IOSDriver:
        return self._driver

    @property
    def udid(self) -> str:
        return self._udid

    def close(self):
        try:
            self._driver.close()
        except Exception:
            pass
