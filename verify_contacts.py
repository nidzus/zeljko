"""Checks on transit-to-natal contacts."""
import sys
sys.path.insert(0, ".")

import swisseph as swe

from backend import contacts, ephemeris, timeplace, transits

results = []
BG = (44.7866, 20.4489)
START = swe.julday(2026, 8, 28, 0.0)
END = swe.julday(2028, 8, 28, 0.0)


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


m = timeplace.resolve(1988, 3, 12, 16, 30, *BG)
chart = ephemeris.compute_chart(m.julian_day_ut, *BG)
found = contacts.find(chart, START, END)

print("=" * 72)
print("1. The aspect angles match the classical drishti")
check("everything makes a conjunction and a 7th",
      contacts._aspect_angles("Venus") == {0.0: "conjunction",
                                           180.0: "7th aspect"})
mars = contacts._aspect_angles("Mars")
check("Mars adds the 4th and 8th at 90 and 210 degrees",
      mars.get(90.0) == "4th aspect" and mars.get(210.0) == "8th aspect",
      ", ".join(f"{a:.0f}={n}" for a, n in sorted(mars.items())))
jup = contacts._aspect_angles("Jupiter")
check("Jupiter adds the 5th and 9th at 120 and 240",
      jup.get(120.0) == "5th aspect" and jup.get(240.0) == "9th aspect")
sat = contacts._aspect_angles("Saturn")
check("Saturn adds the 3rd and 10th at 60 and 270",
      sat.get(60.0) == "3rd aspect" and sat.get(270.0) == "10th aspect")

print()
print("=" * 72)
print("2. Every reported contact is genuinely exact at the moment given")
print("   The separation at that instant must equal the aspect's angle.")
angle_of = {"conjunction": 0.0, "3rd aspect": 60.0, "4th aspect": 90.0,
            "5th aspect": 120.0, "7th aspect": 180.0, "8th aspect": 210.0,
            "9th aspect": 240.0, "10th aspect": 270.0}
worst, worst_c = 0.0, None
for c in found:
    target = (chart.ascendant.longitude if c.natal == "Lagna"
              else chart.get(c.natal).longitude)
    lon = transits.state(c.jd, c.transiting, chart.ayanamsa_name)[0]
    error = abs((lon - target - angle_of[c.aspect] + 180) % 360 - 180)
    if error > worst:
        worst, worst_c = error, c
check("all contacts are exact to well under an arcminute",
      worst < 1 / 60,
      f"largest error {worst * 3600:.1f} arcsec, on {worst_c.transiting} "
      f"{worst_c.aspect} to natal {worst_c.natal}")

print()
print("=" * 72)
print("3. Aspects yield far more than conjunctions alone")
print("   This is why conjunctions on their own were not worth building.")
conj_only = [c for c in found if c.aspect == "conjunction"]
slow_conj = [c for c in conj_only if c.transiting in ("Jupiter", "Saturn")]
check("aspects multiply the count several times over",
      len(found) > 5 * len(slow_conj),
      f"{len(found)} contacts, of which only {len(slow_conj)} are "
      f"conjunctions of Jupiter or Saturn")
check("enough to time with", len(found) > 30, f"{len(found)} over 24 months")

print()
print("=" * 72)
print("4. Retrogression produces repeat passes, reported separately")
by_key = {}
for c in found:
    by_key.setdefault((c.transiting, c.natal, c.aspect), []).append(c)
triples = {k: v for k, v in by_key.items() if len(v) >= 3}
check("some contacts are made three times", triples,
      "; ".join(f"{k[0]} {k[2]} to natal {k[1]}" for k in list(triples)[:3]))
if triples:
    key = list(triples)[0]
    passes = sorted(triples[key], key=lambda c: c.jd)
    check("the passes are distinct dates in order",
          all(a.jd < b.jd for a, b in zip(passes, passes[1:])),
          " -> ".join(p.as_dict()["date"] for p in passes))
    check("and the middle pass is the retrograde one",
          passes[1].retrograde,
          "forward, back over it, then forward again")

print()
print("=" * 72)
print("5. Results are ordered and complete")
check("sorted by date", all(a.jd <= b.jd for a, b in zip(found, found[1:])))
check("each names the natal house it touches",
      all(1 <= c.natal_house <= 12 for c in found))
points = {c.natal for c in found}
check("the ascendant is included as a natal point", "Lagna" in points,
      f"{len(points)} distinct natal points touched")

print()
print("=" * 72)
print("6. The transiting set can be narrowed")
only_saturn = contacts.find(chart, START, END, transiting=("Saturn",))
check("asking for one graha returns only that one",
      {c.transiting for c in only_saturn} == {"Saturn"},
      f"{len(only_saturn)} Saturn contacts")
to_moon = contacts.find(chart, START, END, natal_points=("Moon",))
check("and one natal point returns only that one",
      {c.natal for c in to_moon} == {"Moon"},
      f"{len(to_moon)} contacts to the natal Moon")

print()
print("=" * 72)
print("7. The summary explains what it is showing")
s = contacts.summary(chart, START, END)
check("count matches the contacts listed", s["count"] == len(s["contacts"]))
check("repeat passes are called out", s["repeated_passes"])
check("and the degree-exact refinement is admitted",
      "whole-sign relation" in s["note"],
      "drishti is classically by sign; taking it to the degree is what "
      "yields a date")

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
