"""
Single dispatch entry point for a PyInstaller-frozen build (issue #46 --
source-protection work). Bundling every Python entry point (web/app.py,
src/main.py, src/main_ios.py, src/run_regression.py, src/capture_logs.py)
as its own separate frozen executable would duplicate the entire Python
runtime + dependency set once per entry point; dispatching by argv[1]
from one frozen executable avoids that.

AK supports both Android and iOS, so this has one more mode than the MA
sibling project's dispatcher: --main-ios. It also has a mode MA has no
need for at all: --pymobiledevice3, which dispatches into
pymobiledevice3's own CLI (see src/app_root.py's pymobiledevice3_argv()
for why: sys.executable under a frozen build is this binary, not a
python interpreter, so `python -m pymobiledevice3 ...` doesn't work
anymore -- this mode reroutes that same invocation through this same
dispatcher instead).

Usage (only meaningful once actually frozen -- see web/app.py's and
src/driver_ios.py's subprocess spawn logic, which only takes this path
when sys.frozen is set):
    AKApp --web
    AKApp --main --config path/to.yaml [...other src/main.py args]
    AKApp --main-ios --config path/to.yaml [...]
    AKApp --run-regression [...]
    AKApp --capture-logs --device <id> --out <dir>
    AKApp --pymobiledevice3 usbmux list
    AKApp --smoke-test

Does not change anything about running the project unfrozen -- nothing
else imports or invokes this file in that mode.
"""
import sys

_MODES = {
    "--web": ("web.app", "main"),
    "--main": ("src.main", "main"),
    "--main-ios": ("src.main_ios", "main"),
    "--run-regression": ("src.run_regression", "main"),
    "--capture-logs": ("src.capture_logs", "main"),
    "--pymobiledevice3": ("pymobiledevice3.__main__", "main"),
    "--smoke-test": ("scripts.smoke_test", "main"),
}


def _dispatch():
    if len(sys.argv) < 2 or sys.argv[1] not in _MODES:
        modes = ", ".join(_MODES)
        print(f"usage: {sys.argv[0]} <{'|'.join(_MODES)}> [entry-point args...]",
              file=sys.stderr)
        print(f"  (available modes: {modes})", file=sys.stderr)
        sys.exit(2)

    mode = sys.argv[1]
    module_name, func_name = _MODES[mode]
    # Strip our own dispatch flag so the target entry point's own argparse
    # (or, for pymobiledevice3, Typer reading sys.argv itself) sees exactly
    # the arguments it expects, as if it had been invoked directly.
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    import importlib
    module = importlib.import_module(module_name)
    result = getattr(module, func_name)()
    # src/capture_logs.py's main() returns an int exit code (its own
    # `if __name__ == "__main__": sys.exit(main())` relies on this) --
    # preserve that here since callers check the subprocess returncode.
    # The other modes' main()s all return None, which sys.exit(None)
    # treats as a normal 0 exit -- safe either way.
    sys.exit(result)


if __name__ == "__main__":
    _dispatch()
