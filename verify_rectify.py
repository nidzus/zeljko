"""Checks on rectification.

The important property is not that it finds an answer -- it is that it refuses
to when the evidence does not support one.
"""
import sys
sys.path.insert(0, ".")

import tempfile
from pathlib import Path

from backend import dasha, ephemeris, rectify, timeplace
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


def fresh(confidence=TimeConfidence.REMEMBERED, minute=30):
    store = Store(Path(tempfile.mkdtemp()) / "rect.db")
    pid = store.add_person("Reference")
    store.add_chart(pid, 1988, 3, 12, 16, minute, 0, "Belgrade, RS", *BG,
                    confidence)
    return store, pid


print("=" * 72)
print("1. With too few events it declines rather than guessing")
store, pid = fresh()
store.add_life_event(pid, "2011-04-15", "Changed career")
p = rectify.rectify(store, pid)
check("refuses on two events or fewer", not p.discriminating and p.best is None,
      p.verdict[:96])
check("and says what is needed", "five to ten" in p.verdict)

print()
print("=" * 72)
print("2. Random events do not produce a confident answer")
print("   Dates picked with no relation to this chart's dashas. A method that")
print("   always finds something would claim a birth time from noise.")
store, pid = fresh()
for d, t in [("1994-02-11", "Started school"), ("2003-07-22", "Moved house"),
             ("2009-11-30", "Bought a car"), ("2015-03-08", "Took up running"),
             ("2018-06-19", "Changed phone")]:
    store.add_life_event(pid, d, t)
p = rectify.rectify(store, pid)
check("the run completes and ranks candidates", len(p.candidates) > 0,
      f"{len(p.candidates)} candidates over a +/-{p.window_minutes} min window")
print(f"       verdict: {p.verdict[:150]}")
check("a non-discriminating result is labelled as such, not dressed up",
      p.discriminating is False or "candidate to test" in p.verdict)

print()
print("=" * 72)
print("3. Events placed ON this chart's dasha changes are recovered")
print("   Build the dasha boundaries for a known birth time, invent events")
print("   sitting on them, and see whether that time scores best.")
store, pid = fresh(minute=30)
row = store.active_chart_row(pid)
chart = store.compute(row)
tree = dasha.compute(chart.get("Moon").longitude, row["julian_day_ut"], levels=2)

# Antardasha starts falling in adult life, used as synthetic turning points.
starts = []
for maha in tree.periods[:6]:
    for antar in maha.children:
        when = antar.start
        if 2000 <= when.year <= 2024:
            starts.append(when)
starts = starts[:6]
for i, when in enumerate(starts):
    store.add_life_event(pid, when.strftime("%Y-%m-%d"),
                         f"Turning point {i + 1}", significance=5)
p = rectify.rectify(store, pid, step_minutes=1.0)
check("events on the boundaries are recognised", p.best is not None
      and len(p.best.aligned) >= 4,
      f"{len(p.best.aligned)} of {len(starts)} events aligned")
check("the true time scores at or near the top",
      abs(p.best.offset_minutes) <= 2,
      f"best offset {p.best.offset_minutes:+.0f} min "
      f"({p.best.birth_time}), score {p.best.score:.2f}")
check("and it is reported as discriminating", p.discriminating,
      p.verdict[:110])

print()
print("=" * 72)
print("4. Candidates are ranked, and each shows what it rests on")
check("sorted by score, best first",
      [c.score for c in p.candidates] == sorted(
          (c.score for c in p.candidates), reverse=True))
check("each carries its lagna", all(c.lagna for c in p.candidates))
check("the best names the events it aligns", bool(p.best.aligned),
      p.best.aligned[0] if p.best.aligned else "")

print()
print("=" * 72)
print("5. A window spanning two lagnas is flagged as different charts")
store2, pid2 = fresh(confidence=TimeConfidence.VAGUE)
for i, when in enumerate(starts):
    store2.add_life_event(pid2, when.strftime("%Y-%m-%d"), f"Event {i}")
wide = rectify.rectify(store2, pid2, step_minutes=15.0)
check("more than one lagna appears across a wide window",
      len(wide.lagna_options) > 1, ", ".join(wide.lagna_options))
check("and the verdict says these are different charts",
      "different charts" in wide.verdict)

print()
print("=" * 72)
print("6. Nothing is ever written")
before = [dict(r) for r in store.chart_versions(pid)]
rectify.rectify(store, pid)
after = [dict(r) for r in store.chart_versions(pid)]
check("the stored chart is untouched", before == after,
      f"{len(after)} version(s), unchanged")
check("the proposal says so explicitly",
      "Nothing has been changed" in p.as_dict()["note"])

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
