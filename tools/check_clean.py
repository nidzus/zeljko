#!/usr/bin/env python3
"""Privacy check: keep personal data and secrets out of the public repository.

    python tools/check_clean.py --staged   what is about to be committed (pre-commit hook)
    python tools/check_clean.py --all      every tracked file (check.py, pre-push hook)

Blocks:
- files that belong in the data folder: databases, readings, exports, PDFs,
  .env, CLAUDE.local.md and the per-machine configs;
- secrets: API keys and tokens;
- links to someone's claude.ai artifacts;
- paths inside someone's home folder, and email addresses;
- the name and birth date of every person in this machine's databases, read
  live, so a family name cannot slip in even if nobody thought to list it;
- any line of private-words.txt in the data folder: a surname, an email, a
  street -- anything that must never appear in shared files. A line starting
  with "!" marks a word as harmless instead, for a name that is also an
  ordinary word.

Findings are reported by file and line and never quoted, so the report itself
leaks nothing. Exit code 1 when anything is found. Standard library only.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from backend import paths  # noqa: E402

MAX_BYTES = 2_000_000

BLOCKED_PATH = re.compile(
    r"(^|/)(data|exports|readings|Website)/"
    r"|\.(db|sqlite3?|pdf)$|\.db\.bak|(^|/)\.env$|private-words"
    r"|(^|/)CLAUDE\.local\.md$|(^|/)\.jyotisha\.json$|(^|/)\.mcp\.json$"
    r"|(^|/)settings(\.local)?\.json$",
    re.I)

CONTENT = [
    ("a secret value", re.compile(
        r'"(access_token|refresh_token|client_secret|api_key)"\s*:\s*"(?!\.\.\.|…|<)[^"]{8,}"')),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("an Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}")),
    ("an AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a link to a claude.ai artifact", re.compile(
        r"claude\.ai/(code/)?artifact/[A-Za-z0-9-]{8,}")),
    ("a home-folder path", re.compile(
        r"([A-Za-z]:\\\\?[Uu]sers\\\\?|/Users/|/home/)"
        r"(?!<|\$|%|name\b|you\b|me\b|runner\b)[A-Za-z0-9._-]{2,}")),
    ("an email address", re.compile(
        r"\b[A-Za-z0-9._%+-]+@(?!(?i:example\.(com|org)|anthropic\.com"
        r"|users\.noreply\.github\.com)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]


def fold(text: str) -> str:
    """Lower case, accents removed: "Ångström" and "angstrom" are the same word."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def tracked(staged: bool) -> list[str] | None:
    cmd = (["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
           if staged else ["git", "ls-files"])
    try:
        out = subprocess.run(cmd, cwd=APP, capture_output=True, text=True)
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return [f for f in out.stdout.splitlines() if f]


def content(path: str, staged: bool) -> bytes:
    if staged:
        return subprocess.run(["git", "show", f":{path}"], cwd=APP,
                              capture_output=True).stdout
    return (APP / path).read_bytes()


def _rows(db: Path, query: str) -> list:
    if not db.exists():
        return []
    try:
        con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
        try:
            return con.execute(query).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []


def _date_patterns(iso: str) -> list[str]:
    """One birth date in the ways it could be written down."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", (iso or "").strip())
    if not m:
        return []
    y, mo, d = m.groups()
    mo_, d_ = str(int(mo)), str(int(d))
    return [rf"\b{y}-{mo}-{d}\b",
            rf"\b0?{d_}\.\s?0?{mo_}\.\s?{y}\b",
            rf"\b0?{d_}/0?{mo_}/{y}\b",
            rf"\b{y}/0?{mo_}/0?{d_}\b",
            rf"\b{y},\s*0?{mo_},\s*0?{d_}\b"]       # as the code writes it


def personal_patterns() -> tuple[list[tuple[str, re.Pattern]], int]:
    """Everything personal this machine knows about, as (label, pattern)."""
    data = paths.data_dir()
    harmless, words = set(), []
    words_file = data / "private-words.txt"
    if words_file.exists():
        for line in words_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("!"):
                harmless.add(fold(line[1:].strip()))
            elif len(line) >= 3:
                words.append(fold(line))

    names, dates = set(), set()
    for db in (data / "jyotisha.db", data / "shared.db"):
        for (name,) in _rows(db, "SELECT name FROM person"):
            names.add(fold(name or "").strip())
            names.update(t for t in re.split(r"[^\w]+", fold(name or "")) if len(t) >= 3)
        for (name, email) in _rows(db, "SELECT display_name, email FROM account WHERE is_owner = 0"):
            names.update(t for t in re.split(r"[^\w]+", fold(name or "")) if len(t) >= 3)
            if email:
                words.append(fold(email))
        for (born,) in _rows(db, "SELECT birth_date FROM chart"):
            dates.add(born)

    found = []
    for n in sorted(names - harmless):
        if n:
            found.append(("a name from your databases",
                          re.compile(rf"(?<!\w){re.escape(n)}(?!\w)")))
    for born in sorted(dates):
        for p in _date_patterns(born):
            found.append(("a birth date from your databases", re.compile(p)))
    for w in words:
        if w not in harmless:
            found.append(("a word from private-words.txt", re.compile(re.escape(w))))
    return found, len(names - harmless) + len(dates) + len(words)


def main() -> int:
    staged = "--all" not in sys.argv
    files = tracked(staged)
    if files is None:
        print("Privacy check: not a git repository here, nothing to check.")
        return 0
    personal, known = personal_patterns()
    me = "tools/check_clean.py"
    problems = []
    for f in files:
        if not staged and not (APP / f).exists():
            continue                    # deleted, not yet committed
        if BLOCKED_PATH.search(f):
            problems.append(f"{f}: this kind of file belongs in the data folder, not the app")
            continue
        data = content(f, staged)
        if len(data) > MAX_BYTES:
            problems.append(f"{f}: {len(data) // 1000} kB is suspiciously large for the app")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        # This file holds the generic patterns themselves, so only the
        # personal ones apply to it.
        for haystack, checks in ((text, [] if f == me else CONTENT),
                                 (fold(text), personal)):
            for label, rx in checks:
                for m in rx.finditer(haystack):
                    line = haystack.count("\n", 0, m.start()) + 1
                    problems.append(f"{f}:{line}: {label}")
    if problems:
        print("Privacy check FAILED. Nothing personal goes into the app repository:\n")
        for p in sorted(set(problems)):
            print("  -", p)
        print("\nMove personal content to the data folder (see README.md), then try again.")
        return 1
    scope = "staged" if staged else "all tracked"
    print(f"Privacy check passed ({len(files)} {scope} files, "
          f"{known} personal names, dates and words looked for).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
