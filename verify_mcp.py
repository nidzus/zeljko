"""Checks on the MCP server: the same gate, plus memory in and out."""
import sys
sys.path.insert(0, ".")

import asyncio
import tempfile
from pathlib import Path

from backend import mcp_server as srv
from backend.confidence import TimeConfidence
from backend.store import Store

results = []
BG = (44.7866, 20.4489)


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


# Point the server at a scratch database rather than the real one.
store = Store(Path(tempfile.mkdtemp()) / "mcp.db")
srv._store = store
srv._runners.clear()

print("=" * 72)
print("1. With no profile yet, tools say what to do rather than crashing")
try:
    srv.chart_context()
    check("empty database is handled", False, "it returned instead of raising")
except Exception as e:
    check("empty database is handled", "create_profile" in str(e), str(e)[:90])

pid = store.add_person("Reference", relation="self")
store.add_chart(pid, 1988, 3, 12, 16, 30, 0, "Belgrade, RS", *BG,
                TimeConfidence.REMEMBERED)

print()
print("=" * 72)
print("2. The tool surface is what Claude will actually see")
schemas = asyncio.run(srv.mcp.list_tools())
names = sorted(t.name for t in schemas)
expected = sorted(["list_people", "chart_context", "dasha_at", "transits_at",
                   "events_between", "divisional_chart", "past_decisions",
                   "record_decision", "record_choice", "record_outcome",
                   "add_life_event", "search_places",
                   "parse_coordinates", "create_profile",
                   "panchanga_for", "graha_strength", "transit_support",
                   "yogas_in_chart", "aspects_on_house",
                   "propose_rectification", "apply_rectification",
                   "chart_image", "saturn_from_moon", "personal_day",
                   "graha_shadbala", "transit_contacts", "test_birth_time",
                   "correct_profile", "remove_profile", "back_up_data",
                   "set_current_place"])
check("every tool is registered", names == expected, ", ".join(names))
check("each tool carries a description",
      all(t.description for t in schemas))

print()
print("=" * 72)
print("3. The server tells Claude how to behave")
ins = srv.mcp.instructions
check("the advisor rules are served as instructions", "never calculate" in ins.lower())
check("it is told to read the journal first", "past_decisions" in ins)
check("it is told to write decisions back", "record_decision" in ins)

print()
print("=" * 72)
print("4. One profile resolves without being named")
check("person_id is optional when unambiguous", srv._resolve(None) == pid)
other = store.add_person("Partner", relation="partner")
store.add_chart(other, 1990, 7, 4, 9, 15, 0, "Vienna, AT", 48.2082, 16.3738,
                TimeConfidence.TO_THE_HOUR)
try:
    srv._resolve(None)
    check("several profiles force a choice", False, "it guessed instead")
except Exception as e:
    check("several profiles force a choice", "person_id" in str(e), str(e)[:88])
check("naming one still works", srv._resolve(pid) == pid)

print()
print("=" * 72)
print("5. The gate behaves exactly as it does in the app")
d9 = srv.divisional_chart(varga=9, person_id=pid)
check("navamsa refused on a Â±15 min birth time", d9.get("refused") is True,
      d9.get("reason", "")[:88])
dasha = srv.dasha_at(date="2026-11-15", person_id=pid)
check("dasha dates arrive already rounded",
      dasha["date_precision"] == "to the month",
      "; ".join(f"{p['lord']} {p['begins']}" for p in dasha["periods"]))

print()
print("=" * 72)
print("6. Context carries the chart, the permissions and the life events")
srv.add_life_event(happened_on="2011-04-15", title="Changed career",
                   category="career", person_id=pid)
ctx = srv.chart_context(person_id=pid)
for label, needle in [("the lagna", "Lagna"),
                      ("the permitted claims", "PERMITTED CLAIMS"),
                      ("the life events", "Changed career")]:
    check(f"context includes {label}", needle in ctx)

print()
print("=" * 72)
print("7. Memory round-trips: write a decision, read it back, close the loop")
saved = srv.record_decision(
    question="Should I take the offer abroad?",
    verdict="Wait until December; the terms are not yet visible.",
    question_type="career", confidence_note="moderate",
    window_opens="2026-12-01", window_closes="2027-06-30",
    relied_on=["Saturn retrograde in the 8th until 11 December",
               "antardasha changes in December 2026"],
    person_id=pid)
did = saved["decision_id"]
srv.record_choice(decision_id=did, chose="Waited")
srv.record_outcome(decision_id=did, outcome="Better terms in the new year",
                   rating=2)

past = srv.past_decisions(person_id=pid)
check("the decision comes back", len(past) == 1 and past[0]["decision_id"] == did)
check("with the choice and the outcome attached",
      past[0]["chose"] == "Waited" and past[0]["outcome_rating"] == 2,
      f"{past[0]['question']} -> {past[0]['chose']} -> "
      f"{past[0]['outcome']} ({past[0]['outcome_rating']:+d})")
check("and what it relied on was stored",
      len(store.citations(did)) == 2,
      "; ".join(c["claim"] for c in store.citations(did)))
check("the reliability at the time was frozen with it",
      "to the month" in store.decisions(pid)[0]["reliability"])

print()
print("=" * 72)
print("8. A second profile keeps its own gate, not the first one's")
d9_other = srv.divisional_chart(varga=9, person_id=other)
rel_other = store.reliability(store.active_chart_row(other))
check("the partner's Â±30 min chart is gated separately",
      d9_other.get("refused") is True and rel_other.window_minutes == 30,
      f"partner window Â±{rel_other.window_minutes} min, "
      f"dates {rel_other.date_precision}")
check("past decisions do not leak between profiles",
      srv.past_decisions(person_id=other) == [])

print()
print("=" * 72)
print("9. Onboarding can happen entirely in Claude, without the web app")
hits = srv.search_places(query="Belgrade")
check("city search works over MCP", any(h["name"] == "Belgrade" for h in hits),
      f"{len(hits)} matches")
coords = srv.parse_coordinates(text="44 47 11.8 N, 20 26 56 E")
check("pasted coordinates are read and located",
      abs(coords["latitude"] - 44.7866) < 1e-3
      and coords["timezone"] == "Europe/Belgrade",
      f"{coords.get('formatted')} in {coords.get('timezone')}")
check("nonsense coordinates report an error rather than guessing",
      "error" in srv.parse_coordinates(text="near the sea"))

made = srv.create_profile(
    name="Third", birth_date="1975-06-20", birth_time="08:45",
    place_name="Nis, RS", latitude=43.3209, longitude=21.8958,
    time_confidence="EXACT")
check("a profile is created with its chart", "person_id" in made,
      f"lagna {made.get('lagna')}")
check("and it points at the next step", "life event" in made.get("next", ""))

bad = srv.create_profile(
    name="Bad", birth_date="1975-06-20", birth_time="08:45",
    place_name="x", latitude=1.0, longitude=1.0, time_confidence="PRETTY_SURE")
check("an invented confidence level is refused", "error" in bad,
      bad.get("error", "")[:80])

print()
print("=" * 72)
print("10. A birth time that never existed is surfaced during onboarding")
gap = srv.create_profile(
    name="Gap", birth_date="2024-03-31", birth_time="02:30",
    place_name="Belgrade, RS", latitude=44.7866, longitude=20.4489,
    time_confidence="EXACT")
check("the clocks-forward gap is reported back, not resolved silently",
      any("never occurred" in w for w in gap["warnings"]),
      gap["warnings"][0] if gap["warnings"] else "no warning given")

print()
print("=" * 72)
print("11. A mistake in a profile is corrected without losing anything")
third = made["person_id"]
srv.record_decision(question="Made under the uncorrected chart?",
                    verdict="Yes.", person_id=third)
before = store.active_chart_row(third)
fixed = srv.correct_profile(note="Year was mistyped; certificate says 1976.",
                            birth_date="1976-06-20", name="Third Corrected",
                            person_id=third)
after = store.active_chart_row(third)
versions = store.chart_versions(third)
check("the corrected date is the active chart",
      after["birth_date"] == "1976-06-20" and fixed.get("chart_id") == after["id"],
      fixed.get("birth", str(fixed)[:90]))
check("the earlier version is kept, and the new one points back at it",
      len(versions) == 2 and after["derived_from_id"] == before["id"]
      and fixed["previous_version_kept"] == before["id"])
check("what was not mentioned is carried over unchanged",
      after["birth_time"] == before["birth_time"]
      and after["place_name"] == before["place_name"]
      and after["time_confidence"] == before["time_confidence"])
check("the reason is stored with the new version",
      "certificate" in (after["rectification_note"] or ""))
check("the name is corrected and the profile answers to it",
      srv._resolve("Third Corrected") == third)
check("the journal entry survives, still tied to the chart it was made under",
      [d["chart_id"] for d in store.decisions(third)] == [before["id"]])
copy = Path(fixed.get("safety_copy", "missing"))
check("a safety copy was taken first, in archive/ beside the database",
      copy.exists() and copy.parent == store.path.parent / "archive"
      and "correct-profile" in copy.name, copy.name)
check("a changed place without coordinates is refused, not guessed",
      "error" in srv.correct_profile(note="moved", place_name="Elsewhere",
                                     person_id=third)
      and len(store.chart_versions(third)) == 2)
check("a correction with no note or nothing to change is refused",
      "error" in srv.correct_profile(note=" ", name="X", person_id=third)
      and "error" in srv.correct_profile(note="why", person_id=third)
      and srv._resolve("Third Corrected") == third)
check("an unreadable date is refused and the name left alone",
      "error" in srv.correct_profile(note="why", birth_date="20/06/1976",
                                     name="Renamed", person_id=third)
      and srv._resolve("Third Corrected") == third)

print()
print("=" * 72)
print("12. Removing a profile takes two steps and leaves a way back")
gap_id = gap["person_id"]
srv.add_life_event(happened_on="2030-01-01", title="Something", person_id=gap_id)
preview = srv.remove_profile(person_id="Gap")
check("the first call deletes nothing and says what would go",
      preview["deleted"] is False and preview["would_delete"]["life_events"] == 1
      and preview["would_delete"]["chart_versions"] == 1
      and any(p["id"] == gap_id for p in store.people()), str(preview["would_delete"]))
wrong = srv.remove_profile(person_id="Gap", confirm_name="Reference")
check("a confirmation naming a different profile deletes nothing",
      wrong["deleted"] is False and any(p["id"] == gap_id for p in store.people()))
people_before = len(store.people())
gone = srv.remove_profile(person_id="Gap", confirm_name="gap")
check("with the name confirmed, the profile and all under it are gone",
      gone["deleted"] is True and len(store.people()) == people_before - 1
      and store.db.execute("SELECT COUNT(*) FROM chart WHERE person_id=?",
                           (gap_id,)).fetchone()[0] == 0
      and store.db.execute("SELECT COUNT(*) FROM life_event WHERE person_id=?",
                           (gap_id,)).fetchone()[0] == 0)
check("the other profiles and their journals are untouched",
      len(srv.past_decisions(person_id=pid)) == 1
      and len(store.decisions(third)) == 1)
import sqlite3
copy = Path(gone.get("safety_copy", "missing"))
kept = sqlite3.connect(copy).execute(
    "SELECT COUNT(*) FROM person WHERE name='Gap'").fetchone()[0] if copy.exists() else 0
check("the copy taken just before still holds the removed profile",
      kept == 1 and "remove-profile" in copy.name, copy.name)
try:
    srv.remove_profile(person_id="Gap")
    check("a removed profile is simply not there afterwards", False)
except Exception as e:
    check("a removed profile is simply not there afterwards",
          "No profile named" in str(e))
check("a profile with a journal can be removed too",
      srv.remove_profile(person_id=third, confirm_name="Third Corrected")["deleted"]
      and store.db.execute("SELECT COUNT(*) FROM decision WHERE person_id=?",
                           (third,)).fetchone()[0] == 0)

print()
print("=" * 72)
print("13. A backup on request")
dest = Path(tempfile.mkdtemp()) / "backups"
done = srv.back_up_data(folder=str(dest))
saved_file = Path(done["file"])
check("the backup is a dated file in the folder asked for",
      saved_file.exists() and saved_file.parent == dest
      and saved_file.name.startswith("jyotisha-"), saved_file.name)
names_in_copy = {r[0] for r in sqlite3.connect(saved_file).execute(
    "SELECT name FROM person")}
check("it holds the same profiles as the live database",
      names_in_copy == {p["name"] for p in store.people()},
      ", ".join(sorted(names_in_copy)))
check("and the run is written to the backup log",
      "OK" in (dest / "backup-log.txt").read_text(encoding="utf-8"))
blocker = Path(tempfile.mkdtemp()) / "a-file"
blocker.write_text("x")
try:
    srv.back_up_data(folder=str(blocker / "sub"))
    check("a folder that cannot be used is reported, not swallowed", False)
except Exception as e:
    check("a folder that cannot be used is reported, not swallowed",
          "backup folder" in str(e), str(e).splitlines()[0])
check("the backup tool is kept off the shared server",
      srv.back_up_data in srv.LOCAL_TOOLS and srv.back_up_data not in srv.TOOLS
      and srv.remove_profile in srv.TOOLS and srv.correct_profile in srv.TOOLS)

print()
print("=" * 72)
print("14. Days and clock times are for where the person is, already converted")
print("    A made-up person born in Lisbon who now lives in Los Angeles. The")
print("    tools once answered in universal time for the birthplace, and for")
print("    a plain date gave the day before.")
import datetime as _dt
from zoneinfo import ZoneInfo as _Zone
far = srv.create_profile(name="Faraway Test", birth_date="1980-03-04",
                         birth_time="10:15", place_name="Lisbon",
                         latitude=38.72509, longitude=-9.1498,
                         time_confidence="exact")["person_id"]
ASKED = "2026-03-10"                      # a Tuesday
born = srv.panchanga_for(ASKED, person_id=far)
check("with no current place it answers for the birthplace, and warns",
      born["computed_for"] == "Lisbon" and "BIRTHPLACE" in born["place_warning"])
check("a plain date gives that date's own day, not the one before",
      born["sunrise"].startswith(ASKED) and born["vara"]["english"] == "Tuesday",
      f"{born['sunrise']}, {born['vara']['english']}")
check("no time is left in universal time for someone to convert",
      " UT" not in str(born) and "(UTC+00:00)" in born["sunrise"])
saved = srv.set_current_place("Los Angeles, US", person_id=far)
check("the place the person lives in is saved, with its timezone",
      saved["timezone"] == "America/Los_Angeles"
      and store.current_place(far)["name"] == "Los Angeles, US")
now = srv.panchanga_for(ASKED, person_id=far)
check("the day is then worked out for that place, without being told again",
      now["computed_for"] == "Los Angeles, US" and "place_warning" not in now
      and now["sunrise"].startswith(ASKED) and now["vara"]["english"] == "Tuesday",
      f"sunrise {now['sunrise']}")
check("in that place's clock time, summer time included",
      now["sunrise"].endswith("(UTC-07:00)")
      and "06:30" < now["sunrise"][11:16] < "07:45",
      "9 March 2026 is two days into US summer time")


def _instant(stamp):
    """A stamped time back to the instant it names, for comparing."""
    hh, mm = int(stamp[-6:-4]), int(stamp[-3:-1])
    off = _dt.timedelta(hours=hh, minutes=mm) * (-1 if stamp[-7] == "-" else 1)
    return _dt.datetime.fromisoformat(stamp[:16]) - off


check("the same moment reads the same once both are put on one clock",
      _instant(now["tithi"]["ends"]) == _instant(
          srv.panchanga_for(ASKED, person_id=far, place="Los Angeles, US")
          ["tithi"]["ends"])
      and now["tithi"]["ends"] == _dt.datetime.fromisoformat(
          _instant(now["tithi"]["ends"]).isoformat() + "+00:00").astimezone(
          _Zone("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M") + " (UTC-07:00)")
tokyo = srv.panchanga_for(ASKED, person_id=far, place="Tokyo")
check("a place named in the call wins for that call only",
      tokyo["computed_for"] == "Tokyo, JP" and "(UTC+09:00)" in tokyo["sunrise"]
      and srv.panchanga_for(ASKED, person_id=far)["computed_for"]
      == "Los Angeles, US")
day = srv.personal_day(ASKED, person_id=far)
check("the personal day is that local date, its change time on the same clock",
      day["date"] == ASKED and day["computed_for"] == "Los Angeles, US"
      and day["tara"]["changes_at"].endswith("(UTC-07:00)"),
      day["tara"]["changes_at"])
scan = srv.personal_day(ASKED, days=5, person_id=far)
check("a scan steps through local calendar dates, one each",
      [d["date"] for d in scan["days"]] == [
          "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13", "2026-03-14"])
good = srv.personal_day(ASKED, favourable_only=True, person_id=far)
check("a list of favourable days states its own count",
      good["favourable_count"] == len(good["favourable_days"]))
check("the chart context says where the person is, and counts the events",
      "NOW IN: Los Angeles, US" in srv.chart_context(person_id=far))
check("a place that cannot be found is refused, and nothing is saved",
      "error" in srv.set_current_place("Nowhereville123", person_id=far)
      and store.current_place(far)["name"] == "Los Angeles, US")
srv.set_current_place("", person_id=far)
check("clearing it goes back to the birthplace",
      store.current_place(far) is None
      and srv.panchanga_for(ASKED, person_id=far)["computed_for"] == "Lisbon")
check("the instructions forbid converting, counting and claiming unrun checks",
      "Never convert a time between" in srv.INSTRUCTIONS
      and "tool call in this conversation did it" in srv.INSTRUCTIONS)

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
