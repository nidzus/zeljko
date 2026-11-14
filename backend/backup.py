"""Copies of the personal database: routine backups and safety copies.

Both use SQLite's own backup rather than a file copy, so the copy is whole
even while Claude has the database open.

    run()          a dated backup in the backup folder; a second run on the
                   same day replaces that day's copy
    safety_copy()  a copy in archive/ beside the database, taken before a
                   corrective change, and never replaced or deleted

Standard library only, so jyotisha.py can use it before .venv exists.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from . import paths


def _copy(src: Path, out: Path) -> None:
    """A consistent copy of src at out, or an exception and nothing written."""
    tmp = out.with_name(out.name + ".tmp")
    try:
        s = sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)
        d = sqlite3.connect(tmp)
        try:
            s.backup(d)
        finally:
            s.close()
            d.close()
        tmp.replace(out)
    except (sqlite3.Error, OSError):
        tmp.unlink(missing_ok=True)
        raise


def run(src: Path | None = None, dest: Path | None = None) -> dict:
    """Back up the database. Returns {"ok", "message", "file"}; never raises."""
    src = Path(src) if src else paths.data_dir() / "jyotisha.db"
    dest = Path(dest).expanduser() if dest else paths.backup_dir()
    stamp = dt.date.today().isoformat()
    out = dest / f"jyotisha-{stamp}.db"
    ok, message = False, ""
    if not src.exists():
        message = f"The database is missing:\n  {src}\nNothing was copied."
    else:
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError:
            message = (f"Cannot reach the backup folder:\n  {dest}\n"
                       "If that is a USB or external drive, plug it in and "
                       "run this again.")
        else:
            try:
                _copy(src, out)
                ok, message = True, f"Backed up to:\n  {out}"
            except (sqlite3.Error, OSError) as exc:
                message = f"The copy failed ({exc}). Nothing was written."
    if dest.is_dir():
        now = dt.datetime.now().strftime("%H:%M:%S")
        try:
            with (dest / "backup-log.txt").open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} {now} {'OK  ' if ok else 'FAILED'} "
                         f"{out if ok else ''}\n")
        except OSError:
            pass
    return {"ok": ok, "message": message, "file": str(out) if ok else None}


def safety_copy(db: Path, reason: str) -> Path:
    """Copy db to archive/<name>.bak-<YYYYMMDD>-<reason> beside it.

    An existing copy is never overwritten: a second one on the same day for
    the same reason gets -2, -3 and so on.
    """
    db = Path(db)
    archive = db.parent / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    stem = f"{db.name}.bak-{dt.date.today():%Y%m%d}-{reason}"
    out, n = archive / stem, 1
    while out.exists():
        n += 1
        out = archive / f"{stem}-{n}"
    _copy(db, out)
    return out
