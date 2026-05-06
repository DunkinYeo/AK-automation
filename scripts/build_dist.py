"""
Build distribution ZIPs for Mac and Windows testers.

Creates two ZIPs:
  AccurKardia-Mac-YYYYMMDD.zip
  AccurKardia-Windows-YYYYMMDD.zip

Root structure:
  Mac:     install.command / run.command / STOP.command + automation/
  Windows: install.bat / run.bat / STOP.bat + automation/

Launcher scripts are path-patched on-the-fly so internal references
(web/app.py, requirements.txt) point to automation/ in the ZIP.

Usage:
  python scripts/build_dist.py
  python scripts/build_dist.py --out ~/Desktop
"""

import argparse
import datetime
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today().strftime("%Y%m%d")

# ── Path substitutions ─────────────────────────────────────────────────────
WIN_SUBS = [
    ('"web\\app.py"',               '"automation\\web\\app.py"'),
    ('web\\app.py\n',               'automation\\web\\app.py\n'),
    ('web\\app.py\r\n',             'automation\\web\\app.py\r\n'),
    ('-r requirements.txt',          '-r automation\\requirements.txt'),
    ('"runtime\\platform-tools\\',  '"automation\\runtime\\platform-tools\\'),
    ('"runtime\\android-sdk\\',     '"automation\\runtime\\android-sdk\\'),
    ('%CD%\\runtime"',              '%CD%\\automation\\runtime"'),
    ('%CD%\\runtime\\',             '%CD%\\automation\\runtime\\'),
    ('IF NOT EXIST "logs"',         'IF NOT EXIST "automation\\logs"'),
    ('IF NOT EXIST "runtime"',      'IF NOT EXIST "automation\\runtime"'),
    ('mkdir runtime\n',             'mkdir automation\\runtime\n'),
    ('mkdir runtime\r\n',           'mkdir automation\\runtime\r\n'),
    ('mkdir logs\n',                'mkdir automation\\logs\n'),
    ('mkdir logs\r\n',              'mkdir automation\\logs\r\n'),
]

MAC_SUBS = [
    ('"web/app.py"',                '"automation/web/app.py"'),
    ('$PYTHON web/app.py',          '$PYTHON automation/web/app.py'),
    ('python web/app.py',           'python automation/web/app.py'),
    ('-r requirements.txt',          '-r automation/requirements.txt'),
    ('-f "requirements.txt"',        '-f "automation/requirements.txt"'),
    ('chmod +x scripts/setup_env.sh', 'chmod +x automation/scripts/setup_env.sh'),
    ('bash scripts/setup_env.sh',   'bash automation/scripts/setup_env.sh'),
    ('cd "$(dirname "$0")/.."',     'cd "$(dirname "$0")/../.."'),
    ('"runtime/platform-tools/',    '"automation/runtime/platform-tools/'),
    ('"$PWD/runtime/',              '"$PWD/automation/runtime/'),
    ('"$PWD/runtime"',              '"$PWD/automation/runtime"'),
    ('mkdir -p logs runtime',       'mkdir -p automation/logs automation/runtime'),
    ('mkdir -p runtime',            'mkdir -p automation/runtime'),
]


def _patch(text: str, subs: list) -> str:
    for old, new in subs:
        text = text.replace(old, new)
    return text


def _to_crlf(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\n', '\r\n')


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _add(zf: zipfile.ZipFile, src: Path, arc: str, subs: list = None, crlf: bool = False):
    if not src.exists():
        return
    if subs or crlf:
        content = _patch(_read(src), subs or [])
        if crlf:
            content = _to_crlf(content)
        zf.writestr(arc, content)
    else:
        zf.write(src, arc)


def _add_dir(zf: zipfile.ZipFile, src_dir: Path, arc_prefix: str, subs: list = None):
    SKIP = {"__pycache__", ".pyc", ".DS_Store", ".git", ".pytest_cache"}
    TEXT_EXT = {".py", ".bat", ".sh", ".command", ".txt", ".yaml", ".yml",
                ".html", ".json", ".md", ".cfg", ".ini", ".ps1", ".cmd"}
    for f in src_dir.rglob("*"):
        if f.is_file() and not any(s in str(f) for s in SKIP):
            arc = arc_prefix + "/" + f.relative_to(src_dir).as_posix()
            if subs and f.suffix.lower() in TEXT_EXT:
                zf.writestr(arc, _patch(_read(f), subs))
            else:
                zf.write(f, arc)


EXCLUDE_CONFIG = {"_web_run.yaml", "_web_reg.yaml"}


def _add_config(zf: zipfile.ZipFile, arc_prefix: str):
    config_dir = ROOT / "config"
    if not config_dir.exists():
        return
    for f in sorted(config_dir.iterdir()):
        if f.is_file() and f.name not in EXCLUDE_CONFIG:
            zf.write(f, f"{arc_prefix}/{f.name}")


def build_mac(out_dir: Path) -> Path:
    name = f"AccurKardia-Mac-{TODAY}.zip"
    path = out_dir / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        _add(zf, ROOT / "install.command",    "install.command", MAC_SUBS)
        _add(zf, ROOT / "run.command",        "run.command",     MAC_SUBS)
        _add(zf, ROOT / "STOP.command",       "STOP.command")

        for fname in ["README_MAC_KR.txt", "README_MAC_EN.txt"]:
            _add(zf, ROOT / fname, fname)

        P = "automation"
        _add(zf, ROOT / "requirements.txt",   f"{P}/requirements.txt")
        _add(zf, ROOT / "README.md",           f"{P}/README.md")
        _add_dir(zf, ROOT / "src",     f"{P}/src")
        _add_dir(zf, ROOT / "web",     f"{P}/web")
        _add_dir(zf, ROOT / "scripts", f"{P}/scripts", MAC_SUBS)
        _add_config(zf, f"{P}/config")

    print(f"Mac ZIP:     {path}  ({path.stat().st_size // 1024} KB)")
    return path


def build_windows(out_dir: Path) -> Path:
    name = f"AccurKardia-Windows-{TODAY}.zip"
    path = out_dir / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        _add(zf, ROOT / "install.bat", "install.bat", WIN_SUBS, crlf=True)
        _add(zf, ROOT / "run.bat",     "run.bat",     WIN_SUBS, crlf=True)
        _add(zf, ROOT / "STOP.bat",    "STOP.bat",    crlf=True)

        for fname in ["README_WINDOWS_KR.txt", "README_WINDOWS_EN.txt"]:
            _add(zf, ROOT / fname, fname)

        P = "automation"
        _add(zf, ROOT / "requirements.txt",   f"{P}/requirements.txt")
        _add(zf, ROOT / "README.md",           f"{P}/README.md")
        _add_dir(zf, ROOT / "src",     f"{P}/src")
        _add_dir(zf, ROOT / "web",     f"{P}/web")
        _add_dir(zf, ROOT / "scripts", f"{P}/scripts", MAC_SUBS)
        _add_config(zf, f"{P}/config")

    print(f"Windows ZIP: {path}  ({path.stat().st_size // 1024} KB)")
    return path


def main():
    ap = argparse.ArgumentParser(description="Build AccurKardia distribution ZIPs")
    ap.add_argument("--out", default=str(Path.home() / "Desktop"),
                    help="Output directory (default: ~/Desktop)")
    ap.add_argument("--platform", choices=["mac", "windows", "both"], default="both")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Building distribution ZIPs → {out}\n")
    if args.platform in ("mac", "both"):
        build_mac(out)
    if args.platform in ("windows", "both"):
        build_windows(out)
    print("\nDone.")


if __name__ == "__main__":
    main()
