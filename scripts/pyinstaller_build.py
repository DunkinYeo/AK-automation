"""
Reusable PyInstaller freeze helper (issue #46 -- source-protection work,
ported from the MA sibling project's already-shipped scripts/pyinstaller_build.py).

Freezes scripts/pyinstaller_entry.py (the single multi-mode dispatcher --
see that file's docstring) into a onedir build. Used by
build_dist_bundle_mac_frozen.py / build_dist_bundle_frozen.py instead of
those scripts copying raw src/*.py, web/*.py as loose files.

Things that are NOT obvious from a plain `pyinstaller <script>` and cost
real debugging time to find (2026-09-02~03, first found on MA, then
again here with an AK-specific addition):
  - `--paths <project root>` is required, or PyInstaller's analyzer can't
    locate the src.*/web.* packages at all when resolving --hidden-import
    (fails with "Hidden import 'X' not found" instead of a clear "add
    --paths" hint).
  - Each dynamically-dispatched module (imported via importlib inside
    pyinstaller_entry.py, not a literal top-level `import` statement) must
    be listed explicitly via --hidden-import -- PyInstaller's static
    analysis can't see through the string-keyed _MODES dict dispatch.
  - AK-specific: pymobiledevice3's own CLI (`pymobiledevice3.__main__`)
    dynamically imports each subcommand module
    (`pymobiledevice3.cli.<name>`) the exact same way our own dispatcher
    does -- needs `--collect-submodules pymobiledevice3.cli` or every
    subcommand (`usbmux`, `developer`, `mounter`, ~27 total) raises
    ModuleNotFoundError the first time it's actually invoked, not at
    build time.
  - AK-specific: pymobiledevice3's `inquirer3` -> `readchar` dependency
    calls `importlib.metadata.version("readchar")` at import time to
    self-check its version -- PyInstaller doesn't bundle installed-
    package metadata (dist-info) by default, only the code, so this
    raises PackageNotFoundError unless `--copy-metadata readchar` is
    passed.

config/, web/templates/, and the README*.txt files stay as loose files
copied alongside the frozen executable by the caller -- NOT bundled here
via --add-data. Only the .py application logic gets compiled; this keeps
Flask's template lookup and config file access as plain filesystem reads
via src.app_root.get_app_root(), with no sys._MEIPASS path juggling.

Usage:
    from pyinstaller_build import freeze
    freeze(dist_dir, work_dir, spec_dir)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_HIDDEN_IMPORTS = [
    "web.app",
    "src.main",
    "src.main_ios",
    "src.run_regression",
    "src.capture_logs",
    "pymobiledevice3.__main__",
    "scripts.smoke_test",
]

_COLLECT_SUBMODULES = [
    "pymobiledevice3.cli",
]

_COPY_METADATA = [
    "readchar",
]


def freeze(dist_dir: Path, work_dir: Path, spec_dir: Path, name: str = "AKApp") -> Path:
    """Run PyInstaller and return the path to the frozen onedir output
    (dist_dir / name /)."""
    import PyInstaller.__main__ as pyinstaller_main

    args = [
        str(ROOT / "scripts" / "pyinstaller_entry.py"),
        "--onedir",
        "--name", name,
        "--distpath", str(dist_dir),
        "--workpath", str(work_dir),
        "--specpath", str(spec_dir),
        "--paths", str(ROOT),
        "--noconfirm",
    ]
    for mod in _HIDDEN_IMPORTS:
        args += ["--hidden-import", mod]
    for pkg in _COLLECT_SUBMODULES:
        args += ["--collect-submodules", pkg]
    for pkg in _COPY_METADATA:
        args += ["--copy-metadata", pkg]

    pyinstaller_main.run(args)

    out = dist_dir / name
    if not out.is_dir():
        raise RuntimeError(f"PyInstaller build did not produce {out}")
    return out
