"""Checks on karaka-based rectification testing."""
import sys
sys.path.insert(0, ".")

from backend import dasha, ephemeris, karaka, timeplace, yogas

results = []
VIE = (48.2082, 16.3738)


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


m = timeplace.resolve(1981, 2, 23, 10, 40, *VIE)
chart = ephemeris.compute_chart(m.julian_day_ut, *VIE)
tree = dasha.compute(chart.get("Moon").longitude, m.julian_day_ut, levels=2)


def ev(title, on="2010-01-01", category=None, precision="day", significance=3):
    return {"title": title, "description": "", "happened_on": on,
            "category": category, "precision": precision,
            "significance": significance}


print("=" * 72)
print("1. Events map to the significators tradition assigns them")
for title, category, want_karaka, want_house in [
        ("Father died", "family", "Sun", 9),
        ("Mother died", "family", "Moon", 4),
        ("Got married", "marriage", "Venus", 7),
        ("Daughter born", "family", "Jupiter", 5),
        ("Started a new job", "career", "Saturn", 10),
        ("Moved abroad", "relocation", "Moon", 12),
        ("Had surgery", "health", "Sun", 6)]:
    rule, expected = karaka.expectations(chart, ev(title, category=category))
    lord = yogas.house_lord(chart, want_house)
    ok = want_karaka in expected and lord in expected
    check(f"{title!r} -> {rule}", ok,
          f"expects {', '.join(sorted(expected))} "
          f"(karaka {want_karaka}, {want_house}th lord {lord})")

print()
print("=" * 72)
print("2. A parent's death is about the parent, not about death in general")
rule, expected = karaka.expectations(chart, ev("Father died", category="family"))
check("it resolves to the father, not the 8th house", rule == "father (death)",
      f"rule: {rule}; expects {', '.join(sorted(expected))}")
check("the 8th lord is not dragged in",
      yogas.house_lord(chart, 8) not in expected
      or yogas.house_lord(chart, 8) in {"Sun", yogas.house_lord(chart, 9)},
      "a father's death reads from the 9th and the Sun")

print()
print("=" * 72)
print("3. An event with nothing classical to test against is skipped")
rule, expected = karaka.expectations(chart, ev("Went for a walk"))
check("no rule, no expectation", not expected and not rule)

print()
print("=" * 72)
print("4. Fit counts only testable events, and stays in range")
events = [ev("Father died", "2019-05-14", "family", significance=5),
          ev("Got married", "2006-09-30", "marriage"),
          ev("Daughter born", "2009-04-07", "family"),
          ev("Went for a walk", "2015-01-01")]
r = karaka.fit(chart, tree, events)
check("the untestable event is excluded", r["events_testable"] == 3,
      f"{r['events_testable']} of {len(events)} testable")
check("score is a fraction", 0.0 <= r["score"] <= 1.0, f"{r['score']}")
check("matched never exceeds testable", r["matched"] <= r["events_testable"])
check("each row shows what it expected and what ran",
      all(d.expected and d.running for d in r["detail"]),
      "; ".join(f"{d.rule}: expected {'/'.join(d.expected)}, "
                f"ran {'/'.join(d.running)}" for d in r["detail"][:2]))

print()
print("=" * 72)
print("5. Weighting follows how well an event is dated")
day = karaka.fit(chart, tree, [ev("Father died", "2019-05-14", "family")])
year = karaka.fit(chart, tree,
                  [ev("Father died", "2019-05-14", "family", precision="year")])
check("a day-dated event carries more weight than a year-dated one",
      day["detail"][0].weight > year["detail"][0].weight,
      f"{day['detail'][0].weight} vs {year['detail'][0].weight}")

print()
print("=" * 72)
print("6. The chance level is reported, because the raw score flatters")
print("   Two of nine lords run at any time and a rule names several, so a")
print("   high hit rate is expected even from a wrong chart.")
base = karaka.baseline(chart, events)
check("baseline is a probability", 0.0 < base < 1.0, f"{base}")
check("and it is substantial, not near zero", base > 0.3,
      f"{base:.0%} of events would match by luck alone -- which is why the "
      f"lift above it is what matters, not the score")

print()
print("=" * 72)
print("7. Different birth times give different fits")
other = timeplace.resolve(1981, 2, 23, 9, 35, *VIE)
oc = ephemeris.compute_chart(other.julian_day_ut, *VIE)
ot = dasha.compute(oc.get("Moon").longitude, other.julian_day_ut, levels=2)
a = karaka.fit(chart, tree, events)["score"]
b = karaka.fit(oc, ot, events)["score"]
check("the test discriminates between candidate times", a != b,
      f"10:40 scores {a}, 09:35 scores {b}")

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
