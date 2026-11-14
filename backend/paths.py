"""Where things live. Personal data is never inside the app folder.

The app folder is a public repository. Everything that belongs to the person
running it -- the databases, the API key, readings, exports -- lives in a
separate data folder, found in this order:

    JYOTISHA_HOME     an environment variable, when set (the Claude Desktop
                      extension sets it from its own settings)
    .jyotisha.json    in the app folder, written by `jyotisha.py init`
    ~/jyotisha-data   otherwise

The link file is per machine and never committed. This module uses only the
standard library, so jyotisha.py can import it before .venv exists.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
LINK = APP / ".jyotisha.json"
DEFAULT_DATA = Path.home() / "jyotisha-data"
DEFAULT_BACKUPS = Path.home() / "jyotisha-backups"


def _link() -> dict:
    try:
        return json.loads(LINK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _env(name: str) -> str | None:
    """An environment variable, or None when it is unset or was never filled
    in -- the Claude Desktop extension passes settings through as "${...}"
    placeholders, and one left blank can arrive still looking like that."""
    value = (os.environ.get(name) or "").strip()
    return None if not value or "${" in value else value


def data_dir() -> Path:
    env = _env("JYOTISHA_HOME")
    if env:
        return Path(env).expanduser()
    linked = _link().get("data")
    return Path(linked).expanduser() if linked else DEFAULT_DATA


def family_db() -> Path:
    """The personal database. JYOTISHA_DB overrides, as the tests and the
    MCP configs do."""
    return Path(os.environ.get("JYOTISHA_DB") or data_dir() / "jyotisha.db")


def shared_db() -> Path:
    """The friends' database, for the shared server only."""
    return Path(os.environ.get("JYOTISHA_SHARED_DB") or data_dir() / "shared.db")


def env_file() -> Path:
    return data_dir() / ".env"


def settings() -> dict:
    """Per-person settings, kept in the data folder."""
    try:
        return json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def backup_dir() -> Path:
    """Where routine backups go: settings.json in the data folder, then the
    JYOTISHA_BACKUPS variable (the extension's own setting), then the default."""
    chosen = settings().get("backup_folder") or _env("JYOTISHA_BACKUPS")
    return Path(chosen).expanduser() if chosen else DEFAULT_BACKUPS


def venv_python(root: Path = APP) -> Path:
    """The project's own Python, wherever this OS puts it inside a venv."""
    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"
