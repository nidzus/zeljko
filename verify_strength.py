"""Checks on graha strength and ashtakavarga."""
import sys
sys.path.insert(0, ".")

from backend import ephemeris, strength, timeplace

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


m = timeplace.resolve(1988, 3, 12, 16, 30, *BG)
chart = ephemeris.compute_chart(m.julian_day_ut, *BG)

print("=" * 72)
print("1. Every ashtakavarga table matches its published row total")
print("   These totals are fixed for every chart ever cast, so a")
print("   mistranscribed row cannot hide -- it changes the total.")
for body, want in strength.PUBLISHED_TOTALS.items():
    got = sum(len(v) for v in strength.ASHTAKAVARGA[body].values())
    check(f"{body} totals {want}", got == want, f"got {got}")
total = sum(sum(len(v) for v in t.values())
            for t in strength.ASHTAKAVARGA.values())
check("the whole system totals 337", total == 337, f"got {total}")

print()
print("=" * 72)
print("2. Every table draws on all eight contributors")
for body, table in strength.ASHTAKAVARGA.items():
    ok = sorted(table) == sorted(strength.CONTRIBUTORS)
    houses_valid = all(1 <= h <= 12 for hs in table.values() for h in hs)
    no_dupes = all(len(hs) == len(set(hs)) for hs in table.values())
    check(f"{body}: eight contributors, houses 1-12, no repeats",
          ok and houses_valid and no_dupes)

print()
print("=" * 72)
print("3. A chart's bindus distribute without gaining or losing any")
for body, want in strength.PUBLISHED_TOTALS.items():
    bav = strength.bhinnashtakavarga(chart, body)
    check(f"{body}'s bindus across twelve signs sum to {want}",
          sum(bav) == want and len(bav) == 12,
          f"{bav} = {sum(bav)}")
sav = strength.sarvashtakavarga(chart)
check("sarvashtakavarga sums to 337 for this chart", sum(sav) == 337,
      f"{sav} = {sum(sav)}")
check("no sign holds an impossible count",
      all(0 <= v <= 56 for v in sav),
      f"range {min(sav)} to {max(sav)} across the twelve signs")

print()
print("=" * 72)
print("4. Dignity is read correctly")
for body, sign, deg, expect in [
    ("Sun", strength.ARIES, 10, "exalted"),
    ("Sun", strength.LIBRA, 10, "debilitated"),
    ("Saturn", strength.LIBRA, 20, "exalted"),
    ("Saturn", strength.ARIES, 20, "debilitated"),
    ("Jupiter", strength.CANCER, 5, "exalted"),
    ("Venus", strength.PISCES, 27, "exalted"),
    ("Mars", strength.ARIES, 5, "moolatrikona"),
    ("Mars", strength.SCORPIO, 5, "own sign"),
    ("Sun", strength.SAGITTARIUS, 5, "friendly"),
    ("Sun", strength.CAPRICORN, 5, "inimical"),
]:
    got, note = strength._dignity(body, sign, deg)
    check(f"{body} in {ephemeris.SIGNS[sign][1]} is {expect}", got == expect,
          note)

print()
print("=" * 72)
print("5. Exaltation and debilitation are exactly opposite")
for body, (sign, deg) in strength.EXALTATION.items():
    deb_sign = (sign + 6) % 12
    got, _ = strength._dignity(body, deb_sign, deg)
    check(f"{body} debilitates opposite its exaltation", got == "debilitated",
          f"exalted {ephemeris.SIGNS[sign][1]}, debilitated "
          f"{ephemeris.SIGNS[deb_sign][1]}")

print()
print("=" * 72)
print("6. Combustion is detected, with the tighter retrograde orbs")
burnt, note = strength._combustion("Mercury", 100.0, 95.0, False)
check("Mercury 5 degrees from the Sun is combust", burnt, note[:70])
clear, _ = strength._combustion("Mercury", 130.0, 95.0, False)
check("Mercury 35 degrees away is not", not clear)
inside, _ = strength._combustion("Venus", 104.0, 95.0, False)
outside, _ = strength._combustion("Venus", 104.0, 95.0, True)
check("Venus at 9 degrees is combust direct but clear retrograde",
      inside and not outside,
      "the retrograde orb is 8 degrees rather than 10")
never, _ = strength._combustion("Sun", 95.0, 95.0, False)
check("the Sun is never combust by itself", not never)

print()
print("=" * 72)
print("7. A real chart is assessed end to end")
assessed = strength.assess(chart)
check("every graha is weighed", len(assessed) == 9)
check("each carries a verdict",
      all(s.verdict in ("strong", "moderate", "weak") for s in assessed))
check("each verdict is justified", all(s.reasons for s in assessed))
for s in assessed:
    print(f"       {s.body:<8} {s.verdict:<9} {s.dignity_note}")

print()
print("=" * 72)
print("8. Transit support is per-chart, not a generic rule")
readings = {}
for sign in range(12):
    r = strength.transit_support(chart, "Saturn", sign)
    readings[ephemeris.SIGNS[sign][1]] = (r["own_bindus"], r["reading"])
check("the same graha reads differently across signs",
      len({v[1] for v in readings.values()}) > 1,
      "; ".join(f"{k[:3]} {v[0]}" for k, v in readings.items()))
best = max(readings.items(), key=lambda kv: kv[1][0])
worst = min(readings.items(), key=lambda kv: kv[1][0])
check("the strongest and weakest signs differ",
      best[1][0] > worst[1][0],
      f"best {best[0]} with {best[1][0]} bindus, "
      f"worst {worst[0]} with {worst[1][0]}")
r = strength.transit_support(chart, "Jupiter", 0)
check("the reading carries the house of the nativity",
      1 <= r["house_of_nativity"] <= 12)

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
