# Zeljko, the jyotisha advisor

A personal decision-support tool: questions are answered from a computed
Vedic chart, with every claim tied to a computed fact. `README.md` has the
layout, the design principles and the setup notes — read it before changing
code. This file holds what the README does not.

Notes about the person running this copy (how they like to work, choices
they have made about their own data) are in `CLAUDE.local.md`, which points
into their data folder. It is never committed.

## Two folders

- The app folder is this repository, and it is public. Nothing personal is
  ever written into it.
- The data folder (default `~/jyotisha-data`; `backend/paths.py` finds it)
  holds the databases, old safety copies in `archive/`, `.env`, readings,
  exports, `settings.json`, `private-words.txt` and the person's own
  `CLAUDE.md`. It is not a git repository.
- Anything new that holds personal content goes in the data folder, through
  `paths.py`. Never add a path under the app folder for data.

## How it runs

- The live interface is Claude itself, through the MCP server in
  `backend/mcp_server.py` and the plugin in `jyotisha-plugin/`. This was
  chosen so nothing is billed beyond the Claude subscription.
- `backend/advisor.py` is the paid API route. It is kept working and tested
  but is not used day to day. Do not make features depend on an API key
  without asking. No small or local models.
- The web app (`backend/api.py` + `frontend/`) is view-only: chart and journal.
- `backend/remote.py` is the shared server for invited friends: the same
  tools over HTTP with a sign-in, on its own database. It is run by hand and
  is local-only until the going-online phase. See "Shared server" below.
- Python is the project's own `.venv` (3.11): `.venv/Scripts/python.exe` on
  Windows, `.venv/bin/python` on a Mac. Never the system Python.
- After any code change run `check.py` with that Python; it must end with
  `ALL SUITES PASS`. It includes the privacy check.
- The MCP server loads code at start. After editing anything under
  `backend/`, the Claude session has to be restarted before the tools change.

## Windows and Mac

- `jyotisha.py` does the work. The `.bat` files in the top folder (Windows)
  and the `.command` files in `Mac/` are thin wrappers around it. Change
  behaviour in `jyotisha.py`, and keep both sets of wrappers in step.
- Prefer pointing the person at a double-click file over giving them a
  command.
- `jyotisha.py`, `backend/paths.py`, `tools/repair_paths.py` and
  `tools/check_clean.py` use the standard library only: they must run before
  `.venv` exists.
- `requirements.txt` pins every installed package to its exact version,
  dependencies included. A package only one OS needs carries a marker
  (`pywin32` and `colorama` are Windows-only, `uvloop` is not on Windows). If
  a package is added, pin it there too, or a rebuild will drift.
- `Install or repair` only rebuilds when `.venv` fails an import check;
  `--force` (`/force` on the `.bat`) rebuilds regardless. The old `.venv` is
  set aside as `.venv-old` and put back if the build fails.
- On a Mac, `timezonefinder` is built from source during install and needs
  the Xcode command-line tools. Every other package has a ready-made Mac
  build.
- `.github/workflows/check.yml` runs `jyotisha.py install` on Windows and
  macOS for every push and pull request.

## Version history and publishing

- Public repository: github.com/nidzus/zeljko, AGPL-3.0 (because of the
  Swiss Ephemeris). Only app code is ever pushed.
- `tools/check_clean.py` is the privacy check. It runs before every commit
  and every push (`tools/hooks/`, turned on by `jyotisha.py hooks`, which
  install runs) and inside `check.py`. It blocks data-folder file kinds,
  secrets, email addresses, home-folder paths, every name and birth date in
  the local databases, and every line of `private-words.txt`. Never bypass
  it with `--no-verify`. If it fires, move the content to the data folder.
- Test data is made up. Never use a real person's birth data or life events
  in tests, docs or examples — not even a family member's "just for a test".
- Commit after a change that passes `check.py`. Short message, plain words.
  Before committing, check `git status --short` for anything that should not
  be there.
- If a new kind of private file appears, add it to `.gitignore` and to
  `BLOCKED_PATH` in `check_clean.py` before committing, not after.

## Paths

- `.mcp.json` and `jyotisha-plugin/.mcp.json` hold this machine's absolute
  paths, so they are written on each machine by `tools/repair_paths.py`
  (through `jyotisha.py repair`, and by install) and are not committed. Do not
  edit them by hand.
- The repair also corrects the installed plugin copy at
  `~/.claude/skills/jyotisha/.mcp.json` and an existing `jyotisha` entry in
  Claude Desktop's `claude_desktop_config.json` (on Windows both the ordinary
  and the Microsoft Store location, on a Mac `~/Library/Application
  Support/Claude`). It copies that file to `.bak-<date>` first, never adds an
  entry, and writes nothing when the paths already agree.
- A venv is not relocatable. If the app folder moves, `Repair paths` fixes
  the configs and `Install or repair` rebuilds `.venv`.

## Data

- `jyotisha.db` in the data folder holds the family's birth data, life events
  and the decision journal. It is private: never upload it, publish it, or
  copy profile details into other files.
- Before any bulk or corrective change to the database, copy it to
  `archive/jyotisha.db.bak-<YYYYMMDD>-<reason>` in the data folder. Never
  delete those.
- Routine backups are separate: `Back up data` writes a dated, consistent
  copy to `backup_folder` from the data folder's `settings.json` (default
  `~/jyotisha-backups`), run by hand.
- Profiles and their birth-time status live in the database. Look them up
  with the `list_people` and `chart_context` tools; do not rely on memory or
  on this file.
- Birth times are changed only as new chart versions with a note, never
  edited in place. When the person states a time was witnessed and exact,
  record it as exact and do not reopen the question.
- Only answers recorded with `record_decision` reach the journal. Questions
  asked in other apps or plain chat are not journaled.

## Shared server (friends)

- Two databases that must never mix. `jyotisha.db` is the family's.
  `shared.db` is the friends' and is marked as shared inside the file.
  `Store(path)` with no account opens a personal database as its owner and
  refuses a shared one; `Accounts` and `backend/remote.py` refuse a personal
  one. Never copy rows between them, and never point `JYOTISHA_SHARED_DB` at
  the family file.
- Scoping lives in `backend/store.py`: every public method that takes an id
  calls `_own_person`, `_own_decision` or `_own_conversation` first. A new
  store method or MCP tool must be added to the tables in
  `verify_accounts.py` / `verify_remote.py`, or those suites fail on purpose.
- Tools get their store only from `_get_store()`. Do not open a `Store` or run
  SQL inside a tool.
- Whoever runs the server must not be able to read friends' questions,
  decisions or life events. Those columns are listed in `LOCKED` in
  `store.py` and encrypted in the shared database; names and birth data are
  deliberately readable. If a new column holds something a person says about
  their life, add it to `LOCKED`. Do not add logging of tool arguments or
  results to the server.
- Every page the server shows links to its source code (`SOURCE_URL` in
  `remote.py`, overridable with `JYOTISHA_SOURCE_URL`), as the AGPL requires
  for software used over a network. Someone running a changed version points
  it at their own copy.
- Account management goes through `tools/accounts.py`, never by editing
  `shared.db`. It has no key and cannot read a journal.
- The friends' guidance is served from the three skill files in
  `jyotisha-plugin/skills/` by `backend/guidance.py`. Edit the skill, not a
  copy.
- `Back up data` covers the family database only. `shared.db` has no backup
  routine yet.

## Voice of answers and readings

The single source is `SYSTEM_RULES` in `backend/advisor.py`; the MCP server
reuses it. Change the voice there, not in skills or prompts elsewhere. In
short: verdict first in plain words, then timing, then reasoning where each
technical term follows its plain-language meaning; blunt about the negative;
nothing vague.

## Reading documents (PDF)

- Readings are personal, so their templates live in the data folder:
  `readings/source/<subject>-template.html`. Build with
  `python tools/build_reading.py <subject>` (the project's Python). It prints
  through headless Chrome, checks the result, and writes the PDFs to the data
  folder's `readings/`.
- Each reading has two editions from one template. **Plain** is everyday
  language with no technical terms. **Full** is the same text plus the
  technical panels, wrapped in `<!--TECH-->…<!--/TECH-->`, which teach the
  vocabulary and how each factor bears on the topic.
- Past feedback: earlier drafts were too technical and heavy to read. Keep
  sentences direct, keep disclaimers to a minimum, and do not spend space on
  factors only to say they are inactive.
- The templates are large. Open one only when the task is to edit that
  reading.
