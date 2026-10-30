"""One entry point for setting up and running the advisor, on Windows and Mac.

    python jyotisha.py install [--force]   build .venv if missing or broken, then check
    python jyotisha.py init [folder]       create and link your data folder
    python jyotisha.py where               show where everything is
    python jyotisha.py check               run every verification suite
    python jyotisha.py backup [--quiet]    dated copy of your database
    python jyotisha.py repair [--desktop]  re-point the Claude config files
                                           (--desktop: add to Claude Desktop)
    python jyotisha.py journal             the web app, opened in a browser
    python jyotisha.py accounts [...]      invite and manage friends' accounts
    python jyotisha.py serve               the shared server for friends
    python jyotisha.py hooks               turn on the privacy check before commits

On a Mac use python3. The double-click files in this folder (Windows) and in
Mac/ call these. Standard library only, so it runs before .venv exists.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

from backend import paths  # noqa: E402  (standard library only)

VENV = APP / ".venv"
OLD_VENV = APP / ".venv-old"
VPY = paths.venv_python()
IMPORTS = ("import swisseph, mcp, fastapi, uvicorn, anthropic, dotenv, "
           "timezonefinder, geonamescache, tzdata, pypdf")
WINDOWS = sys.platform == "win32"


def run(cmd: list, **kw) -> int:
    sys.stdout.flush()          # so our own lines stay in order with the child's
    try:
        return subprocess.run([str(c) for c in cmd], cwd=kw.pop("cwd", APP), **kw).returncode
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"Could not start {cmd[0]}: {exc}")
        return 1


def need_venv() -> bool:
    if VPY.exists():
        return True
    print("The environment is missing. Run \"Install or repair\" first.")
    return False


# ------------------------------------------------------------------ install

def _is_311(cmd: list[str]) -> bool:
    try:
        r = subprocess.run([*cmd, "-c", "import sys; sys.exit(sys.version_info[:2] != (3, 11))"],
                           capture_output=True)
    except OSError:
        return False
    return r.returncode == 0


def find_python311() -> list[str] | None:
    """Python 3.11, never the one inside .venv (that may be what is rebuilt).

    3.11 because every package in requirements.txt is pinned to a version
    tested on it, and on Windows the Swiss Ephemeris ships ready-built only
    up to 3.11.
    """
    candidates: list[list[str]] = []
    inside_venv = Path(sys.prefix).resolve() == VENV.resolve()
    if sys.version_info[:2] == (3, 11) and not inside_venv:
        candidates.append([sys.executable])
    base = Path(sys.base_prefix)
    candidates.append([str(base / "python.exe")] if WINDOWS
                      else [str(base / "bin" / "python3.11")])
    if WINDOWS:
        local = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311"
        candidates += [["py", "-3.11"], [str(local / "python.exe")],
                       [r"C:\Program Files\Python311\python.exe"], [r"C:\Python311\python.exe"]]
    else:
        which = shutil.which("python3.11")
        if which:
            candidates.append([which])
        candidates += [["/opt/homebrew/bin/python3.11"], ["/usr/local/bin/python3.11"],
                       ["/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11"]]
    for cmd in candidates:
        if _is_311(cmd):
            return cmd
    return None


def _healthy() -> bool:
    return VPY.exists() and subprocess.run([str(VPY), "-c", IMPORTS],
                                           capture_output=True).returncode == 0


def build_venv() -> bool:
    py = find_python311()
    if py is None:
        print("Python 3.11 is not installed, so the environment cannot be built.")
        if WINDOWS:
            print("Install it from https://www.python.org/downloads/release/python-3119/")
            print("(the 64-bit Windows installer). 3.12 or newer will not work.")
        else:
            print("Install it with:  brew install python@3.11")
            print("or the macOS installer from https://www.python.org/downloads/release/python-3119/")
        return False
    print("Using Python:", " ".join(py))

    if OLD_VENV.exists():
        shutil.rmtree(OLD_VENV, ignore_errors=True)
    if VENV.exists():
        try:
            VENV.rename(OLD_VENV)
        except OSError:
            print("Could not set the old .venv aside because something is using it.")
            print("Close Claude, Claude Desktop and any window using this folder, then")
            print("run this again. Nothing was changed.")
            return False

    steps = [
        ("Creating the environment...", [*py, "-m", "venv", str(VENV)]),
        ("Updating pip...", [VPY, "-m", "pip", "install", "--upgrade", "pip"]),
        ("Installing the pinned packages from requirements.txt...",
         [VPY, "-m", "pip", "install", "-r", "requirements.txt"]),
        ("Confirming every package imports...", [VPY, "-c", IMPORTS]),
    ]
    for label, cmd in steps:
        print(label)
        if run(cmd) != 0:
            print("\nThe new environment could not be built. The reason is above.")
            if not WINDOWS:
                print("On a Mac, if a compiler was missing, run:  xcode-select --install")
            shutil.rmtree(VENV, ignore_errors=True)
            if OLD_VENV.exists():
                OLD_VENV.rename(VENV)
                print("The previous environment was put back as it was.")
            return False
    shutil.rmtree(OLD_VENV, ignore_errors=True)
    print("  all present.\n")
    return True


def install(args: list[str]) -> int:
    force = "--force" in args or "/force" in args
    if force:
        print("--force given, so the environment will be rebuilt.\n")
    elif _healthy():
        print("The existing environment is healthy. Leaving it alone.\n")
    else:
        print("No working environment found. It will be built.\n")
    if (force or not _healthy()) and not build_venv():
        return 1

    init([])
    print()
    repair([])
    print()
    hooks([])
    if "--no-checks" in args:
        return 0
    print("\nRunning every verification suite\n")
    rc = check([])
    print("\nDone. Everything passes." if rc == 0 else "\nSome checks failed. The list is above.")
    print("If anything was rebuilt or moved, restart Claude so it reloads.")
    return rc


# --------------------------------------------------------------- data folder

NOTES = """\
# Your own notes for Claude

Claude reads this file in every session started in the app folder (through
CLAUDE.local.md there). Put here anything personal: how you like to be
advised, who is who in the family, decisions you have made about your data.
It lives in your data folder, so it is never published.
"""


def init(args: list[str]) -> int:
    """Create the data folder and link the app to it. Moves nothing."""
    if args:
        data = Path(args[0]).expanduser().resolve()
    else:
        data = paths.data_dir()
    for sub in ("", "readings", "exports"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    link = {"data": str(data)}
    if paths._link() != link:
        paths.LINK.write_text(json.dumps(link, indent=2) + "\n", encoding="utf-8")
    notes = data / "CLAUDE.md"
    if not notes.exists():
        notes.write_text(NOTES, encoding="utf-8")
    local = APP / "CLAUDE.local.md"
    if not local.exists():
        try:
            shown = "~/" + data.relative_to(Path.home()).as_posix()
        except ValueError:
            shown = data.as_posix()
        local.write_text(f"@{shown}/CLAUDE.md\n", encoding="utf-8")
    print(f"Data folder: {data}")
    if args:
        print("Linked. Run \"repair\" next so Claude finds it.")
    return 0


def where(_args: list[str]) -> int:
    data = paths.data_dir()
    rows = [
        ("App folder", APP, True),
        ("Data folder", data, data.exists()),
        ("Family database", data / "jyotisha.db", (data / "jyotisha.db").exists()),
        ("Shared database", data / "shared.db", (data / "shared.db").exists()),
        ("API key file", paths.env_file(), paths.env_file().exists()),
        ("Backups go to", paths.backup_dir(), paths.backup_dir().exists()),
        ("Environment", VPY, VPY.exists()),
    ]
    for label, path, ok in rows:
        print(f"{label:<16} {path}{'' if ok else '   (not there yet)'}")
    return 0


# -------------------------------------------------------------------- tasks

def check(_args: list[str]) -> int:
    return run([VPY, "check.py"]) if need_venv() else 1


def backup(args: list[str]) -> int:
    """A dated, consistent copy of the family database.

    SQLite's own backup is used rather than a file copy, so the copy is whole
    even if Claude has the database open. A second run on the same day
    replaces that day's copy.
    """
    src = paths.data_dir() / "jyotisha.db"
    dest = paths.backup_dir()
    stamp = dt.date.today().isoformat()
    out = dest / f"jyotisha-{stamp}.db"
    log = dest / "backup-log.txt"
    ok = False
    if not src.exists():
        print(f"The database is missing:\n  {src}\nNothing was copied.")
    else:
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError:
            print(f"Cannot reach the backup folder:\n  {dest}")
            print("If that is a USB or external drive, plug it in and run this again.")
        else:
            tmp = out.with_suffix(".tmp")
            try:
                s = sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)
                d = sqlite3.connect(tmp)
                try:
                    s.backup(d)
                finally:
                    s.close()
                    d.close()
                tmp.replace(out)
                ok = True
                print(f"Backed up to:\n  {out}")
            except (sqlite3.Error, OSError) as exc:
                print(f"The copy failed ({exc}). Nothing was written.")
                tmp.unlink(missing_ok=True)
    if dest.exists():
        now = dt.datetime.now().strftime("%H:%M:%S")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {now} {'OK  ' if ok else 'FAILED'} {out if ok else ''}\n")
    return 0 if ok else 1


def repair(args: list[str]) -> int:
    from tools import repair_paths
    return repair_paths.main(args)


def journal(_args: list[str]) -> int:
    if not need_venv():
        return 1
    url = "http://127.0.0.1:8011/"
    print(f"The journal will open at {url}\nClose this window when you are done.\n")
    threading.Timer(3, webbrowser.open, [url]).start()
    return run([VPY, "-m", "uvicorn", "backend.api:app", "--port", "8011"])


def accounts(args: list[str]) -> int:
    return run([VPY, "tools/accounts.py", *args]) if need_venv() else 1


def serve(_args: list[str]) -> int:
    if not need_venv():
        return 1
    print("This is the server friends connect to. It uses shared.db only, never")
    print("the family database. On this computer it is reachable only from this")
    print("computer.\n")
    return run([VPY, "-m", "backend.remote"])


def hooks(_args: list[str]) -> int:
    """Run the privacy check before every commit and push."""
    if not (APP / ".git").exists():
        print("Privacy check hooks: this folder is not a git repository, skipped.")
        return 0
    rc = run(["git", "config", "core.hooksPath", "tools/hooks"], capture_output=True)
    print("Privacy check hooks: on." if rc == 0 else "Privacy check hooks: could not be set.")
    return rc


COMMANDS = {"install": install, "init": init, "where": where, "check": check,
            "backup": backup, "repair": repair, "journal": journal,
            "accounts": accounts, "serve": serve, "hooks": hooks}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 0 if len(sys.argv) < 2 else 1
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
