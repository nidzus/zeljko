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
  `backend/mcp_server.py` and the plugin in `zeljko-plugin/`. This was
  chosen so nothing is billed beyond the Claude subscription.
- `backend/advisor.py` is the paid API route. It is kept working and tested
  but is not used day to day. Do not make features depend on an API key
  without asking. No small or local models.
- The web app (`backend/api.py` + `frontend/`) is view-only: chart and journal.
- `backend/remote.py` is the shared server for invited friends: the same
  tools over HTTP with a sign-in, on its own database. It is run by hand and
  is local-only until the going-online phase. See "Shared server" below.
- `backend/extension.py` is the same local server packaged as a Claude
  Desktop extension for people who install nothing else. See "Claude Desktop
  extension" below.
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
- `jyotisha.py`, `backend/paths.py`, `backend/backup.py`,
  `tools/repair_paths.py` and `tools/check_clean.py` use the standard library
  only: they must run before
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

- `.mcp.json` and `zeljko-plugin/.mcp.json` hold this machine's absolute
  paths, so they are written on each machine by `tools/repair_paths.py`
  (through `jyotisha.py repair`, and by install) and are not committed. Do not
  edit them by hand.
- The repair also corrects the installed plugin copy at
  `~/.claude/skills/zeljko/` (its files refreshed from `zeljko-plugin/`, its
  `.mcp.json` repointed) and an existing `zeljko` entry in
  Claude Desktop's `claude_desktop_config.json` (on Windows the ordinary
  location, the Microsoft Store one and the newer
  `%LOCALAPPDATA%\Claude-Data\claude_*`; on a Mac `~/Library/Application
  Support/Claude`). It copies that file to `.bak-<date>` first, adds an entry
  only with `--desktop` (the `Add to Claude Desktop` files), and writes
  nothing when the paths already agree. `verify_repair.py` covers it.
- Names: what Claude shows is Zeljko — the MCP server and the plugin are
  `zeljko`, the skills `zeljko:ask`, `zeljko:journal`, `zeljko:onboard`.
  Until 2026-11 they were `jyotisha`; the repair renames an old `jyotisha`
  server entry that runs this app (never duplicates it) and moves
  `~/.claude/skills/jyotisha` to `zeljko`, deleting nothing. The internal
  names stay `jyotisha` on purpose: `jyotisha.py`, `jyotisha.db`,
  `.jyotisha.json`, the `JYOTISHA_*` variables and the default
  `~/jyotisha-data`, because existing installs and the extension find their
  data through them.
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
- A profile can hold where the person lives (`set_current_place`, the
  `now_*` columns on `person`) and one dated stay elsewhere (the `away_*`
  columns: first day to last day). `panchanga_for` and `personal_day` answer
  for the place the person is in on the date asked about: a place named in
  the call, else a stay covering the date, else home, else the birthplace
  with a warning. A stay lapses by itself; travel is recorded as a stay,
  never by overwriting home. Places are readable in the shared database for
  the same reason the birthplace is.
- No tool hands out a clock time in universal time. Every time goes through
  `timeplace.clock()`, in the local time of the place the answer is for, with
  the offset shown; a plain date means that calendar date in that place.
  Claude is told never to convert a time, count a list or claim a check it
  did not run, but an instruction can be ignored: if an answer needs a
  number, a tool must state it. (Found 2026-11-16: Claude miscounted 31 life
  events as 29 and converted times by hand; `panchanga_for` also returned
  the day before the date asked for.)
- Only answers recorded with `record_decision` reach the journal. Questions
  asked in other apps or plain chat are not journaled.

- `correct_profile` and `remove_profile` take that archive copy themselves
  (`Store.safety_copy`) before they change a personal database. Removal is
  two calls: a preview, then the profile's name as confirmation.

## Claude Desktop extension

- The people installing it are not technical. Anything they must do goes on
  the download page (`docs/index.html`) in plain words; the server's
  instructions tell Claude never to ask them for a command or a file edit.
- No setting in `extension/manifest.json` may be `required`, and none may
  carry a `default`. Claude Desktop leaves an extension switched off after
  install, with a grey Save button, while a required setting is empty, and a
  default does not count as filled in (read from Desktop's own code,
  2026-11-15, after version 1.0.0 did exactly that). Empty settings fall back
  to the folders in `paths.py`.
- Claude Desktop's menus move between versions. On 2026-11-15 extensions were
  under Settings → Customize → Connectors, not "Extensions". Do not give a
  menu path from memory; ask for a screenshot.
- Claude Desktop asks permission per tool. Every tool declares whether it
  only reads (`marks()` in `mcp_server.py`); a tool that changes data must be
  named in `WRITES` there. Unmarked, all tools land in one "Other tools"
  group that needs approval one by one.
- A tool registered with `@tool` is offered everywhere, the shared server
  included. `@local_tool` is for tools that need the person's own database
  file (`back_up_data`); the shared server does not offer those.
- `extension/manifest.json` lists every tool by name. Add or rename a tool
  and `verify_extension.py` fails until the manifest matches.
- The version in `extension/manifest.json` is the release switch: pushing a
  version with no release makes `.github/workflows/release.yml` build and
  publish all three files. Raise it only when a release is meant, and ask
  first.
- The frozen program reads `backend/schema.sql` and the skill files from
  beside the code. A new data file the code reads at run time has to be added
  to `freeze()` in `tools/build_extension.py`, or it works in `.venv` and
  fails in the extension.
- The Mac files cannot be tried on Windows. They are tried by the release
  workflow on real Macs, by opening the packed file and running a first
  session; a real install in Claude Desktop on a Mac has not been done from
  here.
- Intel Macs have no ready-made build of `cryptography`, so the release
  workflow compiles it with OpenSSL inside (`OPENSSL_STATIC`). Without that
  the frozen program fails to start. The build also refuses a Mac bundle
  that points at a library from the build machine.
- `Build extension` installs PyInstaller into `.venv`
  (`requirements-build.txt`). It is not needed to run the advisor.

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
  `zeljko-plugin/skills/` by `backend/guidance.py`. Edit the skill, not a
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
