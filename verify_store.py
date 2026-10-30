"""Checks on the storage layer, exercised over a full lifecycle."""
import sys
sys.path.insert(0, ".")

import tempfile
from pathlib import Path

from backend import ephemeris
from backend.confidence import TimeConfidence
from backend.store import Store

results = []


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


db_path = Path(tempfile.mkdtemp()) / "test.db"
store = Store(db_path)

print("=" * 72)
print("1. A person and a chart round-trip")
pid = store.add_person("Reference", relation="self")
cid = store.add_chart(pid, 1988, 3, 12, 16, 30, 0, "Belgrade, RS",
                      44.7866, 20.4489, TimeConfidence.REMEMBERED)
row = store.active_chart_row(pid)
check("chart is stored and active", row["id"] == cid)
check("the resolution was preserved, not recomputed on read",
      row["timezone_name"] == "Europe/Belgrade" and row["utc_offset_hours"] == 1.0,
      f"{row['timezone_name']} {row['utc_offset_hours']:+.2f}h")

print()
print("=" * 72)
print("2. The stored moment reproduces the chart exactly")
stored = store.compute(row)
direct = ephemeris.compute_chart(row["julian_day_ut"], row["latitude"],
                                 row["longitude"], row["ayanamsa"])
check("recomputed chart matches a direct computation",
      stored.ascendant.longitude == direct.ascendant.longitude,
      f"lagna {stored.ascendant.sign_english}")

print()
print("=" * 72)
print("3. Rectification versions rather than overwrites")
rid = store.add_chart(pid, 1988, 3, 12, 16, 37, 0, "Belgrade, RS",
                      44.7866, 20.4489, TimeConfidence.RECTIFIED,
                      derived_from_id=cid,
                      rectification_note="fits the 2011 job change")
versions = store.chart_versions(pid)
check("both versions retained", len(versions) == 2)
check("the original is preserved, flagged inactive",
      versions[0]["id"] == cid and versions[0]["is_active"] == 0)
check("the rectified version is active and points back",
      store.active_chart_row(pid)["id"] == rid
      and versions[1]["derived_from_id"] == cid,
      versions[1]["rectification_note"])

print()
print("=" * 72)
print("4. The reliability gate travels with the stored chart")
rel_remembered = store.reliability(versions[0])
rel_rectified = store.reliability(versions[1])
check("the REMEMBERED version refuses navamsa claims",
      not rel_remembered.allows("navamsa"))
check("permissions are read from the stored confidence, not assumed",
      rel_remembered.window_minutes == 15 and rel_rectified.window_minutes == 3,
      f"{rel_remembered.window_minutes} min vs {rel_rectified.window_minutes} min")

print()
print("=" * 72)
print("5. Life events come back in a deterministic order")
store.add_life_event(pid, "2019-09-01", "Moved abroad", category="relocation")
store.add_life_event(pid, "2011-04-15", "Changed career", category="career",
                     significance=5)
store.add_life_event(pid, "2011-04-15", "Same day, second entry", category="career")
order = [(e["happened_on"], e["id"]) for e in store.life_events(pid)]
check("sorted by date then id", order == sorted(order), str(order))

print()
print("=" * 72)
print("6. The cached prompt prefix is byte-identical between reads")
print("   This is what makes prompt caching work. Any instability here is")
print("   an invisible charge on every question you ever ask.")
a = store.context_prefix(pid)
b = store.context_prefix(pid)
check("two consecutive reads are identical", a == b, f"{len(a)} bytes")
check("contains no volatile content",
      "20" + "26" not in a.replace(row["birth_date"], ""),
      "no timestamps leaked into the stable prefix")

print()
print("=" * 72)
print("7. But it does change when the underlying data changes")
store.add_life_event(pid, "2024-01-05", "Started the project", category="career")
c = store.context_prefix(pid)
check("prefix reflects the new event", c != a and "Started the project" in c)

print()
print("=" * 72)
print("8. A decision runs its full lifecycle")
conv = store.start_conversation(pid, "Berlin contract")
store.add_message(conv, "user", "Should I take the contract in Berlin?")
store.add_message(conv, "assistant", "Wait for Jupiter to enter the 10th.")
did = store.record_decision(
    pid, rid, "Should I take the contract in Berlin?",
    question_type="career", houses_consulted=[10, 1], conversation_id=conv,
    verdict="Favourable after the spring", confidence_note="moderate",
    window_opens="2026-04-01", window_closes="2026-10-01")
store.add_citation(did, "Jupiter enters your 10th",
                   "event", {"body": "Jupiter", "house": 10, "jd": 2460431.5})
store.record_choice(did, "Waited")
store.record_outcome(did, "Better offer arrived in May", rating=2)

d = store.decisions(pid)[0]
check("question, choice and outcome all persisted",
      d["question_type"] == "career" and d["chose"] == "Waited"
      and d["outcome_rating"] == 2,
      f"{d['verdict']} -> {d['chose']} -> {d['outcome']} ({d['outcome_rating']:+d})")
check("the conversation is kept as provenance",
      len(store.messages(conv)) == 2)
check("claims are joined to the computed facts behind them",
      len(store.citations(did)) == 1
      and "Jupiter" in store.citations(did)[0]["fact"])

print()
print("=" * 72)
print("9. Bad input is refused rather than stored")
for label, fn in [
    ("outcome rating out of range", lambda: store.record_outcome(did, "x", 9)),
    ("unknown message role", lambda: store.add_message(conv, "system", "x")),
    ("unknown date precision",
     lambda: store.add_life_event(pid, "2020-01-01", "x", precision="decade")),
    ("missing person", lambda: store.person(999)),
]:
    try:
        fn()
        check(label, False, "it was accepted")
    except (ValueError, KeyError):
        check(label, True)

print()
print("=" * 72)
print("10. A connection survives being used from another thread")
print("   The web server hands one request across thread-pool threads, so a")
print("   store built on one and used on another must still work. FastAPI's")
print("   TestClient does not reproduce this -- only a real server does.")
import threading
thread_result = {}


def use_from_other_thread():
    try:
        thread_result["rows"] = len(store.chart_versions(pid))
    except Exception as exc:            # noqa: BLE001 -- recording it is the test
        thread_result["error"] = f"{type(exc).__name__}: {exc}"


t = threading.Thread(target=use_from_other_thread)
t.start()
t.join()
check("query succeeds from a different thread", "error" not in thread_result,
      thread_result.get("error", f"read {thread_result.get('rows')} chart versions"))

print()
print("=" * 72)
print("11. Deleting a person removes everything belonging to them")
store.db.execute("DELETE FROM person WHERE id=?", (pid,))
store.db.commit()
left = sum(store.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
           for t in ("chart", "life_event", "conversation", "message",
                     "decision", "citation"))
check("no orphaned rows remain", left == 0, f"{left} rows left behind")

store.close()
print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
