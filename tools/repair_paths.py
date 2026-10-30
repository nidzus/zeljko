"""Point the Claude config files at wherever the app and data folders live.

Run after moving or renaming the app folder or the data folder:

    python jyotisha.py repair
    python jyotisha.py repair --desktop    also add the advisor to Claude Desktop

The folders' absolute paths are written into the "jyotisha" server entry of:

    <app>/.mcp.json                           the Claude Code project server
    <app>/jyotisha-plugin/.mcp.json           the plugin's copy
    <home>/.claude/skills/jyotisha/.mcp.json  the installed plugin, if present
    claude_desktop_config.json                Claude Desktop, if it has the entry

The first two are written on each machine and never committed. Claude
Desktop's file is looked for wherever this OS keeps it (on Windows both the
ordinary install and the Microsoft Store one, including the newer
Claude-Data folder). There an existing "jyotisha" entry is corrected, and
one is added only with --desktop. Everything else in that file -- other MCP
servers, other settings -- is left exactly as it was, and the file is copied
to claude_desktop_config.json.bak-<date> before any change.

When the paths are already correct nothing is written at all, so running it
twice is safe.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import paths  # noqa: E402  (standard library only)

SERVER = "jyotisha"


def wanted() -> dict:
    """The jyotisha server entry as it must read for these folders."""
    return {
        "command": str(paths.venv_python(ROOT)),
        "args": ["-m", "backend.mcp_server"],
        "env": {
            "PYTHONPATH": str(ROOT),
            "JYOTISHA_DB": str(paths.data_dir() / "jyotisha.db"),
        },
    }


def desktop_configs(installed: bool = False) -> list[pathlib.Path]:
    """Every Claude Desktop config on this machine.

    installed: also return configs not written yet, where Desktop's own
    folder exists, so --desktop can create the file.
    """
    found = []
    if sys.platform == "darwin":
        found.append(pathlib.Path.home() / "Library" / "Application Support"
                     / "Claude" / "claude_desktop_config.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        found.append(pathlib.Path(appdata) / "Claude" / "claude_desktop_config.json")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        # The Microsoft Store build keeps its own private copy of Roaming,
        # and newer versions move it out to Claude-Data.
        found.extend(sorted((pathlib.Path(local) / "Packages").glob(
            "Claude_*/LocalCache/Roaming/Claude*/claude_desktop_config.json")))
        found.extend(sorted(p / "claude_desktop_config.json" for p in
                            (pathlib.Path(local) / "Claude-Data").glob("claude_*")))
    if installed:
        return [p for p in found if p.exists() or
                (p.parent.is_dir() and any(p.parent.iterdir()))]
    return [p for p in found if p.exists()]


def read_json(path: pathlib.Path) -> dict:
    # utf-8-sig: Claude Desktop may have written a byte-order mark.
    text = path.read_text(encoding="utf-8-sig")
    return json.loads(text) if text.strip() else {}


def patch(path: pathlib.Path, label: str, *, create: bool, add: bool,
          backup: bool) -> str:
    """Correct the jyotisha entry in one config file. Returns a status word.

    create: write the file if it does not exist.
    add:    put the entry in if the file has none.
    """
    if path.exists():
        try:
            config = read_json(path)
        except json.JSONDecodeError as exc:
            print(f"  {label}: NOT VALID JSON, left alone ({exc})")
            return "error"
    elif create:
        config = {}
    else:
        print(f"  {label}: not present, nothing to do")
        return "absent"

    before = (config.get("mcpServers") or {}).get(SERVER) or {}
    if not before and not add:
        print(f"  {label}: has no {SERVER} entry, left alone")
        return "absent"
    want = wanted()

    after = dict(before)
    after["command"] = want["command"]
    after.setdefault("args", want["args"])
    env = dict(after.get("env") or {})
    env["PYTHONPATH"] = want["env"]["PYTHONPATH"]
    env["JYOTISHA_DB"] = want["env"]["JYOTISHA_DB"]
    after["env"] = env

    if after == before:
        print(f"  {label}: already correct, not touched")
        return "unchanged"

    if backup and path.exists():
        stamp = dt.date.today().strftime("%Y%m%d")
        copy = path.with_name(path.name + f".bak-{stamp}")
        shutil.copy2(path, copy)
        print(f"  {label}: copied to {copy.name} first")

    servers = config.setdefault("mcpServers", {})
    servers[SERVER] = after
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    verb = "added" if not before else "updated"
    others = [k for k in servers if k != SERVER]
    kept = f", {len(others)} other server(s) kept" if others else ""
    print(f"  {label}: {verb}{kept}")
    return "changed"


def main(args: list[str] | None = None) -> int:
    add_desktop = "--desktop" in (args or [])
    print(f"App folder:  {ROOT}")
    print(f"Data folder: {paths.data_dir()}")
    print()

    results = [
        patch(ROOT / ".mcp.json", ".mcp.json",
              create=True, add=True, backup=False),
        patch(ROOT / "jyotisha-plugin" / ".mcp.json", "jyotisha-plugin/.mcp.json",
              create=True, add=True, backup=False),
        patch(pathlib.Path.home() / ".claude" / "skills" / SERVER / ".mcp.json",
              "installed plugin (.claude/skills)",
              create=False, add=True, backup=False),
    ]
    desktops = desktop_configs(installed=add_desktop)
    if not desktops:
        print("  Claude Desktop config: not present, nothing to do")
        if add_desktop:
            print("  Claude Desktop does not seem to be installed. Install it,"
                  " open it once, then run this again.")
    for path in desktops:
        # Claude-3p is Desktop's separate third-party-provider mode: an entry
        # there is kept correct, but none is added.
        add = add_desktop and not path.parent.name.endswith("-3p")
        results.append(patch(path, f"Claude Desktop config ({path.parent.name})",
                             create=add, add=add, backup=True))

    print()
    changed = results.count("changed")
    if "error" in results:
        print("Something was wrong with one of the files. See above.")
        return 1
    if changed:
        print(f"{changed} file(s) corrected. Restart Claude so it reads them.")
        if add_desktop:
            print("For Claude Desktop, quit it fully, then open it again: on"
                  " Windows right-click its icon by the clock and choose Quit,"
                  " on a Mac press Cmd+Q.")
    else:
        print("Nothing needed changing. Everything already points here.")

    if not paths.venv_python(ROOT).exists():
        print()
        print("Note: .venv is missing. Run \"Install or repair\" to rebuild it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
