"""
Single source of truth for "the real installation directory" (issue #46,
PyInstaller source-protection work — ported from the MA sibling project,
where this exact module was validated first).

Before this, web/app.py, src/timeline.py, src/scheduler.py,
src/capture_logs.py, src/artifact_manager.py, and src/driver.py each
computed their own ROOT independently via
`Path(__file__).resolve().parent.parent`. That works when running from
real source (unfrozen), but breaks under a PyInstaller-frozen build:
__file__ for a bundled module resolves inside PyInstaller's ephemeral
extraction temp dir (sys._MEIPASS), not the actual, persistent directory
the user installed the app into -- config/output/runtime files written
there would vanish or scatter across temp dirs that don't even agree
with each other module-to-module.

Frozen: use sys.executable's own directory (the actual installed
location, stable across runs). Unfrozen: unchanged behavior for every
current dev/CI/existing-distribution workflow.
"""
import sys
from pathlib import Path


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def pymobiledevice3_argv(*args: str) -> list[str]:
    """
    Build the argv for invoking pymobiledevice3's CLI (AK-only -- MA has
    no iOS support). Unfrozen: `python -m pymobiledevice3 <args>`,
    unchanged. Frozen: sys.executable is our own frozen binary, not a
    python interpreter capable of `-m pymobiledevice3` -- dispatch to it
    via the --pymobiledevice3 mode instead (see
    scripts/pyinstaller_entry.py), which imports and calls
    pymobiledevice3.__main__.main() in-process. That function reads
    sys.argv itself (via Typer), so the dispatcher's generic argv-strip
    handles it the same way as every other mode -- no pymobiledevice3-
    specific code needed there.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pymobiledevice3", *args]
    return [sys.executable, "-m", "pymobiledevice3", *args]
