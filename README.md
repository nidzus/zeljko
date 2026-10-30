# Zeljko

A jyotisha (Vedic astrology) advisor that runs in your own Claude. Ask about a decision —
take the job, move, commit, wait — and get an answer grounded in your
computed Vedic chart, with every claim traceable to a computed fact. It keeps
a journal of what was advised, what you chose and how it turned out, so you
can see over time whether the advice is any good.

> **Heads-up:** this is a tool for thinking a decision through, not
> professional advice of any kind, and it can be wrong. See `NOTICE.md`.

## What it does

- **Set up a profile (`/jyotisha:onboard`):** birth data, how well the birth
  time is actually known, and the life events that can later narrow it down.
- **Ask (`/jyotisha:ask`):** a verdict in plain words first, then the timing,
  then the reasoning — each technical term introduced by what it means.
- **Journal (`/jyotisha:journal`):** past advice, what you chose, and how it
  turned out.
- **Exact computation:** positions, houses and ayanamsas from the Swiss
  Ephemeris; Vimshottari dashas; transits, stations and ingresses;
  panchanga; dignity, shadbala and ashtakavarga; yogas; the divisional
  charts; Sade Sati; whether today is a good day for you.
- **Honest about the birth time:** a chart recorded to the nearest half hour
  is refused the claims that half hour could overturn, and dates are rounded
  to what it can support. Life events can narrow a loose birth time.
- **A view-only web app** for the chart and the journal.
- **Optional shared server** so invited friends can use it from their own
  Claude, each seeing only their own data.

## Privacy: two folders

| | App (this repository) | Your data folder (`~/jyotisha-data`) |
| --- | --- | --- |
| Holds | Code, skills, tests, these notes | Birth data, life events, the decision journal, readings, your API key, your own notes for Claude |
| Shared | Yes, via GitHub | Never. It is not a git repository, and the app never writes personal data into its own folder. |
| Updated by | `git pull` | You and Claude |

- **Claude** reads your data in your own Claude sessions, through your own
  account, the same as anything else you show Claude.
- **Commits:** a privacy check runs before every commit and push. It stops
  personal files and secrets from entering the repository, and also blocks
  every name and birth date from your own databases, read live on your
  machine.

## Install

You need:

- [Claude Code](https://claude.com/claude-code), signed in;
- Python **3.11** (not newer: every package is pinned and tested on it);
- git;
- on a Mac, Apple's command-line tools (`xcode-select --install`), which
  bring git and the compiler one package needs.

**The easy way:** open Claude Code in any folder and paste:

> Install Zeljko, the jyotisha advisor, from https://github.com/nidzus/zeljko into
> my home folder: clone it, run `jyotisha.py install` with Python 3.11, then
> start `/jyotisha:onboard` for me.

**By hand, on Windows:**

```
winget install Python.Python.3.11 Git.Git
git clone https://github.com/nidzus/zeljko.git %USERPROFILE%\zeljko
cd %USERPROFILE%\zeljko
py -3.11 jyotisha.py install
```

**By hand, on macOS:**

```
xcode-select --install
brew install python@3.11
git clone https://github.com/nidzus/zeljko.git ~/zeljko
cd ~/zeljko
python3.11 jyotisha.py install
```

Install builds the environment (`.venv`), creates your data folder, points
Claude's config files at both folders, turns on the privacy check and runs
every test. Afterwards double-click **Ask Jyotisha** (on a Mac, in the `Mac`
folder) and type `/jyotisha:onboard`.

To keep your data somewhere else, run `jyotisha.py init <folder>` and then
`jyotisha.py repair` before you start.

## Everyday use

Double-click files for when you do not want a command line: `.bat` in the top
folder on Windows, `.command` in `Mac/` on a Mac.

| File | Does |
| --- | --- |
| Ask Jyotisha | opens Claude Code with the plugin loaded |
| Open journal | starts the web app and opens the journal in a browser |
| Check everything | runs every test and the privacy check |
| Install or repair | rebuilds `.venv` if it is missing or broken, then checks |
| Back up data | a dated copy of your database to your backup folder |
| Repair paths | re-points the Claude config files at the app and data folders |
| Manage accounts | invite, list, disable, reset or delete a friend's account |
| Start shared server | runs the server friends connect to, on this computer only |
| Try as a test friend | opens Claude Code as a friend would see it |

Inside Claude Code:

| Skill | For |
| --- | --- |
| `/jyotisha:onboard` | set up a profile: birth data, time confidence, life events |
| `/jyotisha:ask` | ask about a decision and get a timed answer |
| `/jyotisha:journal` | review past advice, record choices and outcomes |

The plugin bundles the MCP server, so there is nothing else to configure. To
use the tools from plain Claude Desktop chat too, copy the `jyotisha` entry
from `.mcp.json` (written by install) into Desktop's
`claude_desktop_config.json`; `Repair paths` keeps it correct after that.

## Commands

```
python jyotisha.py install [--force]   build .venv if missing or broken, then check
python jyotisha.py init [folder]       create and link your data folder
python jyotisha.py where               show where everything is
python jyotisha.py check               every test, plus the privacy check
python jyotisha.py backup              dated copy of your database
python jyotisha.py repair              re-point the Claude config files
python jyotisha.py journal             the web app, opened in a browser
python jyotisha.py accounts [...]      invite and manage friends' accounts
python jyotisha.py serve               the shared server for friends
python jyotisha.py hooks               turn on the privacy check before commits
```

Use the project's Python for everything except `install`:
`.venv\Scripts\python.exe` on Windows, `.venv/bin/python` on a Mac.

## Updating

`git pull` in the app folder, then **Install or repair** (it rebuilds the
environment only if the pinned packages changed, and runs the tests). Your
data folder is never touched by an update.

## Your data folder

```
jyotisha-data/
  jyotisha.db         profiles, charts, life events, the decision journal
  shared.db           the friends' database, if you run the shared server
  archive/            safety copies taken before corrective changes
  readings/           reading templates and PDFs
  exports/
  settings.json       e.g. {"backup_folder": "E:\\Jyotisha-Backups"}
  private-words.txt   extra words the privacy check must block
  CLAUDE.md           your own notes for Claude, read in every session
  .env                your Anthropic API key, only for the paid route
```

`jyotisha.py where` shows where everything is. The folder is found from the
`JYOTISHA_HOME` environment variable if set, then the link file
`.jyotisha.json` that `init` writes in the app folder, then `~/jyotisha-data`.

**Backups.** `Back up data` writes `jyotisha-<date>.db` to `backup_folder`
(default `~/jyotisha-backups`) and appends a line to `backup-log.txt` there.
It uses SQLite's own backup, so the copy is whole even while Claude has the
database open; a second run on the same day replaces that day's copy. A copy
on the same drive covers mistakes, not the drive failing — for that, point
`backup_folder` at a different disk.

**If a folder moves.** After moving the app or data folder, run
`Repair paths` (after `init <new folder>` if it was the data folder). A
virtual environment is not relocatable, so after moving the app folder also
run `Install or repair`.

## Sharing with friends

Friends use the advisor from their own Claude subscription, as a custom
connector pointing at a shared server you run. Nothing is billed to you and
no API key is involved.

**Two databases, never mixed.** `jyotisha.db` is yours and is used only by
the plugin, Claude Desktop and the web app. `shared.db` is the friends' and
starts empty. The shared server refuses to start on a personal database, and
has no code that reaches yours.

**Invite-only.** `Manage accounts` creates an account for an email address
and prints a one-time invite code, good for 14 days. The friend enters the
code on the sign-in page, chooses a password, and is shown a recovery code
once. There is no way to create an account without an invitation.

**What you can and cannot read.** In `shared.db`, names and birth data are
readable. Questions, verdicts, choices, outcomes, citations and life events
are encrypted with a key that exists only wrapped under the friend's password,
their recovery code and their live sign-in. Opening the file or a backup shows
gibberish for those. This is not absolute: the server holds the key in memory
while it serves that friend, so whoever runs it could alter the code to
capture content. It protects against reading the file, not against a
dishonest operator.

**Forgotten passwords.** The recovery code sets a new password and keeps
everything. With both lost, "Reset" in the account menu issues a new invite
code; profiles and charts survive, the journal and life events are deleted
because nobody can unlock them.

**Without the plugin.** Friends have no skills installed. The server's
instructions send Claude to its `guidance` tool, which serves the same text as
the three skills in `jyotisha-plugin/`; they are also offered as prompts. Edit
a skill and both routes change.

**Trying it on this computer.** Start `Start shared server` and leave it
open. In `Manage accounts`, invite two made-up addresses. Then start
`Try as a test friend`, choose A, type `/mcp`, pick the server and
Authenticate; a browser opens the sign-in page. Do the same again choosing B
in a second window. Each sees only what it created.

Claude.ai, Claude Desktop and the phone apps cannot reach a server on your
computer: they connect from Anthropic's servers, so the address has to be
public. That is a later phase.

Settings, all optional environment variables: `JYOTISHA_SHARED_DB` (default
`shared.db` in the data folder), `JYOTISHA_PORT` (8765), `JYOTISHA_HOST`
(127.0.0.1), `JYOTISHA_PUBLIC_URL` (`http://localhost:8765`), the address
friends will type, and `JYOTISHA_SOURCE_URL`, the source-code link every page
shows (see "Licence").

## The paid advisor route

Everything above runs on your Claude subscription. `backend/advisor.py` is a
second route through the Anthropic API, kept working and tested but not
needed day to day. To use it, put `ANTHROPIC_API_KEY=...` in `.env` in your
data folder (`.env.example` shows the form); the key never enters the app
folder.

Model `claude-opus-5` at `xhigh` effort with adaptive thinking. Effort is the
dial to turn, not the model: the one call that matters is resolving several
factors pointing different ways into a single honest verdict, and that is what
higher effort buys.

## Principles the code enforces

**No model ever computes.** Everything astronomical comes from Swiss
Ephemeris. Claude interprets values it is handed and cites them; it never
produces a position, a date, or a dasha boundary.

**Charts are versioned, never overwritten.** A rectified birth time is a new
row pointing back at the original, with its reasoning attached.

**Claims are gated by birth-time confidence.** `confidence.py` recomputes the
chart across its uncertainty window and reports which conclusions actually
survive — per chart, not by generic rule. A birth near a sign boundary is
refused house claims that a mid-sign birth of identical confidence is allowed.

**Tools refuse what the chart cannot bear.** Ask for a navamsa on a birth
time known to a quarter hour and the tool returns a refusal with the remedy.
No wording the model chooses gets that data out.

**Precision is removed at source.** When a chart supports dates only to the
month, the dasha tool returns "November 2026". The model cannot overstate
precision, because it never sees a precise date.

**Citations are checked.** Every claim carries a fact id the tool issued.
Invented ids are detected after the fact and are never written to the citation
table — so what is stored is only ever a claim joined to a real computed value.

**The prompt prefix is byte-stable.** Prompt caching is an exact prefix match,
so `store.context_prefix()` must never contain a timestamp or an unordered
query. There is a test for this; it is guarding a recurring bill.

**An account reaches only its own data.** A store is opened for one account
and every method checks ownership before it reads or writes. Someone else's id
gets the same answer as an id that does not exist. `verify_accounts.py` walks
every store method and `verify_remote.py` every tool; both fail if one is
added without being covered.

## Layout

| Path | Layer |
| --- | --- |
| `backend/ephemeris.py` | positions, whole-sign houses, nakshatras, ayanamsas |
| `backend/timeplace.py` | birth data to an exact instant, auditably |
| `backend/dasha.py` | Vimshottari, three levels deep |
| `backend/transits.py` | ingresses, stations, dasha changes |
| `backend/panchanga.py` | the five limbs of a day, with end times |
| `backend/strength.py` | dignity, combustion, digbala, ashtakavarga |
| `backend/yogas.py` | aspects and classical combinations |
| `backend/shani.py` | Sade Sati and the Moon-relative Saturn periods |
| `backend/personalday.py` | Tara bala and Chandra bala: is today good for you |
| `backend/chartsvg.py` | drawing the chart, natal and with transits |
| `backend/divisional.py` | the ten divisional charts, each by its own rule |
| `backend/shadbala.py` | numeric strength, for ranking grahas |
| `backend/contacts.py` | dated transit-to-natal contacts |
| `backend/karaka.py` | testing a birth time against life events by significator |
| `backend/rectify.py` | narrowing a loose birth time against life events |
| `backend/confidence.py` | what a chart is entitled to claim |
| `backend/store.py` | SQLite persistence, always opened for one account |
| `backend/schema.sql` | the tables |
| `backend/paths.py` | where the data folder and everything in it is |
| `backend/vault.py` | keys and locked fields for the shared database |
| `backend/accounts.py` | invitations, sign-in and account management |
| `backend/remote.py` | the shared server: the tools over HTTP, behind a sign-in |
| `backend/guidance.py` | serves the plugin's three skills to people without it |
| `backend/tools.py` | the only tools the advisor may use |
| `backend/advisor.py` | the interpretive layer -- the one place a model runs |
| `jyotisha.py` | install, check, backup and the rest, on Windows and Mac |
| `tools/check_clean.py` | the privacy check, run before commits and pushes |
| `tools/repair_paths.py` | rewrites the per-machine Claude config paths |
| `tools/accounts.py` | the account menu behind `Manage accounts` |
| `tools/build_reading.py` | prints a reading template to Plain and Full PDFs |
| `sensitivity.py` | where a given chart's fragile boundaries are |
| `verify_*.py`, `check.py` | the tests; `check.py` runs them all |

## Changing it

Run `python check.py` with the project's Python after any change; it must
end with `ALL SUITES PASS`. The same install-and-test runs on Windows and
macOS on GitHub for every push. The tests use only made-up people; never put
a real person's birth data or life events in a test or an example.

Improvements are welcome as pull requests.

## Known limits

Pre-1900 births carry residual error no software can remove: birth times
recorded from sundials are in apparent solar time, which differs from mean
time by up to 16 minutes depending on the date. We assume mean time.

Published sankranti times differ between the Drik and Vakya panchanga
traditions by more than our computational precision. Disagreement with a given
almanac is not necessarily an error in either.

## Licence

GNU Affero General Public License, version 3 (`LICENSE`), because the Swiss
Ephemeris it is built on is used under that licence. Use it, change it, share
it. If you run a changed version for other people over a network, offer them
its source: point `JYOTISHA_SOURCE_URL` at your copy. Credits and the
third-party licences are in `NOTICE.md`.
