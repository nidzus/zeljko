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
                   "graha_shadbala", "transit_contacts", "test_birth_time"])
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
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
