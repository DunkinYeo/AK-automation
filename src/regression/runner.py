import dataclasses
import logging
import time
from typing import Callable

log = logging.getLogger(__name__)


@dataclasses.dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration_s: float
    screenshot: str | None = None


class TestRunner:
    def __init__(self, drv, artifacts=None):
        self.drv = drv
        self.artifacts = artifacts
        self.results: list[TestResult] = []

    def assert_true(self, condition: bool, message: str):
        if not condition:
            raise Exception(message)

    def assert_false(self, condition: bool, message: str):
        if condition:
            raise Exception(message)

    def fail(self, message: str):
        raise Exception(message)

    @staticmethod
    def _clean_message(e: Exception) -> str:
        msg = str(e)
        first_line = msg.split('\n')[0].strip()
        # Selenium exceptions: "Message: ...\nStacktrace:\n..."
        if first_line.startswith('Message:'):
            body = first_line[len('Message:'):].strip()
            if not body:
                # Empty message — extract exception type from stacktrace
                for line in msg.split('\n'):
                    line = line.strip()
                    if 'NoSuchElement' in line or 'could not be located' in line:
                        return "Element not found on screen"
                    if 'StaleElement' in line or 'stale element' in line.lower():
                        return "Stale element (screen changed)"
                    if 'TimeoutException' in line or 'timeout' in line.lower():
                        return "Timeout waiting for element"
                return "Unexpected Appium error"
            if 'could not be located' in body:
                return "Element not found on screen"
            if 'stale element' in body.lower():
                return "Stale element (screen changed)"
            return body[:80]
        return first_line[:80]

    def run(self, test_fn: Callable) -> TestResult:
        name = (test_fn.__doc__ or test_fn.__name__).strip()
        log.info("[TC] %s", name)
        start = time.monotonic()
        screenshot = None
        try:
            test_fn(self.drv, self)
            duration = time.monotonic() - start
            result = TestResult(name=name, passed=True, message="PASS", duration_s=duration)
            log.info("  PASS (%.1fs)", duration)
        except Exception as e:
            duration = time.monotonic() - start
            try:
                screenshot = self.drv.screenshot(f"fail_{test_fn.__name__}")
            except Exception:
                pass
            result = TestResult(
                name=name, passed=False, message=self._clean_message(e),
                duration_s=duration, screenshot=screenshot
            )
            log.warning("  FAIL: %s (%.1fs)", e, duration)
        self.results.append(result)
        return result

    def run_all(self, tests: list[Callable]) -> dict:
        for t in tests:
            self.run(t)
        return self.summary()

    def summary(self) -> dict:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        log.info("=" * 50)
        log.info("Regression: %d/%d passed", passed, total)
        for r in self.results:
            icon = "PASS" if r.passed else "FAIL"
            log.info("  [%s] %s", icon, r.name)
            if not r.passed:
                log.info("       -> %s", r.message)
                if r.screenshot:
                    log.info("       screenshot: %s", r.screenshot)
        log.info("=" * 50)
        return {"total": total, "passed": passed, "failed": total - passed, "results": self.results}
