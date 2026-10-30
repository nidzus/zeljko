"""Checks on the HTTP layer, driven through a real client."""
import sys
sys.path.insert(0, ".")

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import app, get_store
from backend.store import Store

results = []
DB = Path(tempfile.mkdtemp()) / "api.db"


def override():
    with Store(DB) as s:
        yield s


app.dependency_overrides[get_store] = override
client = TestClient(app)


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


print("=" * 72)
print("1. The interface can discover its own vocabulary")
r = client.get("/api/reference")
ref = r.json()
check("reference endpoint responds", r.status_code == 200)
check("confidence levels carry their windows",
      {c["name"] for c in ref["time_confidence"]} >= {"EXACT", "VAGUE"},
      ", ".join(f"{c['name']}={c['window_minutes']}m"
                for c in ref["time_confidence"]))
check("ayanamsas offered", "LAHIRI" in ref["ayanamsas"], str(ref["ayanamsas"]))

print()
print("=" * 72)
print("2. Place search")
r = client.get("/api/places", params={"q": "Belgrade"})
hits = r.json()
check("finds Belgrade", any(h["name"] == "Belgrade" for h in hits),
      f"{len(hits)} results, first {hits[0]['name'] if hits else '-'}")
check("short queries are refused", client.get(
    "/api/places", params={"q": "B"}).status_code == 422)

print()
print("=" * 72)
print("3. Pasted coordinates -- the escape hatch for places not in the database")
r = client.post("/api/places/coords", json={"text": '44°47\'11.8"N 20°26\'56"E'})
body = r.json()
check("DMS parsed and located", r.status_code == 200
      and abs(body["latitude"] - 44.7866) < 1e-3
      and body["timezone"] == "Europe/Belgrade",
      f"{body.get('formatted')} in {body.get('timezone')}")
check("nonsense refused with 422",
      client.post("/api/places/coords", json={"text": "near the sea"}).status_code == 422)

print()
print("=" * 72)
print("4. Onboarding a person and a chart")
pid = client.post("/api/people", json={"name": "Reference"}).json()["id"]
r = client.post(f"/api/people/{pid}/chart", json={
    "year": 1988, "month": 3, "day": 12, "hour": 16, "minute": 30,
    "place_name": "Belgrade, RS", "latitude": 44.7866, "longitude": 20.4489,
    "time_confidence": "REMEMBERED"})
created = r.json()
check("chart created", r.status_code == 201)
check("the resolution is reported back, not hidden",
      created["timezone_name"] == "Europe/Belgrade"
      and created["utc_offset_hours"] == 1.0,
      f"offset {created['utc_offset_hours']:+.2f}h, "
      f"LMT override {created['used_local_mean_time']}")

print()
print("=" * 72)
print("5. The chart comes back complete")
chart = client.get(f"/api/people/{pid}/chart").json()
check("lagna present", chart["lagna"]["sign_english"] == "Leo",
      f"{chart['lagna']['formatted']} {chart['lagna']['sign_english']}")
check("nine grahas", len(chart["positions"]) == 9,
      ", ".join(p["name"] for p in chart["positions"]))
check("twelve houses, first is the lagna sign",
      len(chart["houses"]) == 12
      and chart["houses"][0]["sign_index"] == chart["lagna"]["sign_index"])
check("every graha carries a house", all(1 <= p["house"] <= 12
                                         for p in chart["positions"]))

print()
print("=" * 72)
print("6. The reliability gate rides along with the chart")
rel = chart["reliability"]
check("permissions returned per claim kind", set(rel["permitted"]) >= {
    "house_placement", "navamsa", "shashtiamsa"})
check("REMEMBERED allows houses but refuses navamsa",
      rel["permitted"]["house_placement"] and not rel["permitted"]["navamsa"],
      f"dates may be stated {rel['date_precision']}, "
      f"drift {rel['dasha_drift_days']:.0f} days")

print()
print("=" * 72)
print("7. A birth time that never existed is surfaced, not silently resolved")
pid2 = client.post("/api/people", json={"name": "Gap"}).json()["id"]
r = client.post(f"/api/people/{pid2}/chart", json={
    "year": 2024, "month": 3, "day": 31, "hour": 2, "minute": 30,
    "place_name": "Belgrade, RS", "latitude": 44.7866, "longitude": 20.4489,
    "time_confidence": "EXACT"})
check("flagged as nonexistent", r.json()["time_nonexistent"] is True,
      "clocks went forward at 02:00 that morning")

print()
print("=" * 72)
print("8. Life events")
client.post(f"/api/people/{pid}/events", json={
    "happened_on": "2011-04-15", "title": "Changed career",
    "category": "career", "significance": 5})
client.post(f"/api/people/{pid}/events", json={
    "happened_on": "2019-09-01", "title": "Moved abroad"})
events = client.get(f"/api/people/{pid}/events").json()
check("stored and returned in date order",
      [e["happened_on"] for e in events] == ["2011-04-15", "2019-09-01"])
check("bad precision refused", client.post(
    f"/api/people/{pid}/events",
    json={"happened_on": "2020-01-01", "title": "x",
          "precision": "decade"}).status_code == 422)

print()
print("=" * 72)
print("9. Dasha")
d = client.get(f"/api/people/{pid}/dasha", params={"at": "2024-06-01"}).json()
check("three nested levels running", len(d["running"]) == 3,
      " / ".join(p["lord"] for p in d["running"]))
check("nine mahadashas listed", len(d["mahadashas"]) == 9)
check("date precision travels with the dates",
      d["date_precision"] in ("exact dates", "to the week", "to the month",
                              "to the season", "none"),
      d["date_precision"])

print()
print("=" * 72)
print("10. Timeline")
tl = client.get(f"/api/people/{pid}/timeline", params={
    "start": "2024-01-01", "end": "2025-01-01",
    "bodies": "Jupiter,Saturn"}).json()
check("events returned", len(tl) > 0, f"{len(tl)} events")
check("sorted by time", [e["when"] for e in tl] == sorted(e["when"] for e in tl))
check("ingresses are placed in houses",
      all(e["house"] for e in tl if e["kind"] == "ingress"),
      "; ".join(f"{e['body']} {e['detail']} (h{e['house']})"
                for e in tl if e["kind"] == "ingress"))
check("unknown body refused", client.get(
    f"/api/people/{pid}/timeline",
    params={"start": "2024-01-01", "end": "2024-02-01",
            "bodies": "Pluto"}).status_code == 422)

print()
print("=" * 72)
print("11. The cacheable context block is exposed for inspection")
c1 = client.get(f"/api/people/{pid}/context").json()
c2 = client.get(f"/api/people/{pid}/context").json()
check("identical across requests", c1["text"] == c2["text"],
      f"{c1['bytes']} bytes")
check("states what may be claimed", "PERMITTED CLAIMS:" in c1["text"])

print()
print("=" * 72)
print("12. Bad input is refused with the right status")
for label, resp in [
    ("unknown confidence level", client.post(f"/api/people/{pid}/chart", json={
        "year": 1988, "month": 3, "day": 12, "hour": 16, "minute": 30,
        "place_name": "x", "latitude": 44.0, "longitude": 20.0,
        "time_confidence": "PROBABLY"})),
    ("unknown ayanamsa", client.post(f"/api/people/{pid}/chart", json={
        "year": 1988, "month": 3, "day": 12, "hour": 16, "minute": 30,
        "place_name": "x", "latitude": 44.0, "longitude": 20.0,
        "time_confidence": "EXACT", "ayanamsa": "MADE_UP"})),
    ("impossible latitude", client.post(f"/api/people/{pid}/chart", json={
        "year": 1988, "month": 3, "day": 12, "hour": 16, "minute": 30,
        "place_name": "x", "latitude": 200.0, "longitude": 20.0,
        "time_confidence": "EXACT"})),
    ("chart for a person who does not exist",
     client.get("/api/people/9999/chart")),
]:
    ok = resp.status_code in (404, 422)
    check(label, ok, f"HTTP {resp.status_code}")

print()
print("=" * 72)
print("13. The decision journal, and the loop that makes it worth keeping")
store = Store(DB)
chart_id = store.active_chart_row(pid)["id"]
did = store.record_decision(pid, chart_id, "Should I take the offer abroad?",
                            question_type="career", verdict="Wait until December.",
                            window_opens="2026-12-01", window_closes="2027-06-30")
store.add_citation(did, "Saturn retrograde in the 8th", "transit", {"body": "Saturn"})
store.close()

journal = client.get(f"/api/people/{pid}/decisions").json()
check("the decision is listed", len(journal) == 1 and journal[0]["id"] == did)
check("an unanswered decision is flagged open",
      journal[0]["open"] is True and journal[0]["chose"] is None,
      "open decisions are the ones to come back to")
check("citations are counted", journal[0]["citations"] == 1)

r = client.post(f"/api/decisions/{did}/choice", json={"chose": "Waited"})
check("recording a choice succeeds", r.status_code == 200)
r = client.post(f"/api/decisions/{did}/outcome",
                json={"outcome": "Better terms in January", "rating": 2})
check("recording an outcome succeeds", r.status_code == 200)

closed = client.get(f"/api/people/{pid}/decisions").json()[0]
check("the loop closes", closed["open"] is False
      and closed["chose"] == "Waited" and closed["outcome_rating"] == 2,
      f"{closed['chose']} -> {closed['outcome']} ({closed['outcome_rating']:+d})")

check("an out-of-range rating is refused", client.post(
    f"/api/decisions/{did}/outcome",
    json={"outcome": "x", "rating": 9}).status_code == 422)
check("an empty choice is refused", client.post(
    f"/api/decisions/{did}/choice", json={"chose": ""}).status_code == 422)
check("a decision that does not exist is a 404",
      client.get("/api/decisions/9999").status_code == 404)

detail = client.get(f"/api/decisions/{did}").json()
check("detail carries the citations joined to facts",
      len(detail["citations"]) == 1 and "Saturn" in detail["citations"][0]["claim"])

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
