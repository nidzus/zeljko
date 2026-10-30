"""Checks on the event finder."""
import sys; sys.path.insert(0, ".")
import swisseph as swe
from backend import timeplace, ephemeris, dasha, transits

results = []


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


Y0 = swe.julday(2024, 1, 1, 0.0)
Y1 = swe.julday(2025, 1, 1, 0.0)

print("=" * 72)
print("1. Sanity check against a published almanac date")
print("   Mesha Sankranti 2024 -- the Sun entering sidereal Aries -- is")
print("   quoted around 13 April 2024, 21:13 IST = 15:43 UT. Treat this as")
print("   approximate: Drik and Vakya panchangas disagree by more than the")
print("   tolerance here. Check 3 is the actual precision test.")
sun = transits.find_ingresses(swe.julday(2024, 4, 1, 0.0),
                              swe.julday(2024, 4, 30, 0.0), "Sun")
aries = [e for e in sun if e.sign_index == 0][0]
target = swe.julday(2024, 4, 13, 15 + 43 / 60)
err_min = abs(aries.jd - target) * 1440
check("Sun's Aries ingress is the right day, near the right hour", err_min < 20,
      f"computed {aries.when:%Y-%m-%d %H:%M} UT, published 15:43 UT "
      f"(off by {err_min:.1f} min)")

print()
print("=" * 72)
print("2. The Sun makes exactly twelve ingresses in a year")
sun_year = transits.find_ingresses(Y0, Y1, "Sun")
check("twelve solar ingresses", len(sun_year) == 12, f"found {len(sun_year)}")
gaps = [b.jd - a.jd for a, b in zip(sun_year, sun_year[1:])]
check("spaced about a month apart", all(29 < g < 32 for g in gaps),
      f"{min(gaps):.2f} to {max(gaps):.2f} days")

print()
print("=" * 72)
print("3. Every ingress lands on a sign boundary")
worst = 0.0
for e in sun_year:
    lon, _ = transits.state(e.jd, "Sun")
    worst = max(worst, min(lon % 30, 30 - (lon % 30)))
check("all within an arcminute of 0 or 30 degrees", worst < 1 / 60,
      f"largest deviation {worst * 3600:.1f} arcsec")

print()
print("=" * 72)
print("4. Mercury retrogrades about three times a year")
merc = transits.find_stations(Y0, Y1, "Mercury")
retro = [e for e in merc if "retrograde" in e.detail]
check("three retrograde stations in 2024", len(retro) == 3,
      "; ".join(f"{e.when:%d %b}" for e in retro))
check("each retrograde is matched by a direct station",
      len(merc) - len(retro) in (2, 3, 4), f"{len(merc)} stations total")

print()
print("=" * 72)
print("5. Speed genuinely reverses across a station")
s = merc[0]
before = transits.state(s.jd - 0.5, "Mercury")[1]
after = transits.state(s.jd + 0.5, "Mercury")[1]
check("motion changes direction", (before < 0) != (after < 0),
      f"{before:+.4f} deg/day before, {after:+.4f} after")

print()
print("=" * 72)
print("6. The nodes never station -- they are always retrograde")
check("no Rahu stations", transits.find_stations(Y0, Y1, "Rahu") == [])
check("Rahu's motion is negative", transits.state(Y0, "Rahu")[1] < 0,
      f"{transits.state(Y0, 'Rahu')[1]:+.5f} deg/day")

print()
print("=" * 72)
print("7. Ingresses are placed against the nativity's houses")
m = timeplace.resolve(1988, 3, 12, 16, 30, 44.7866, 20.4489)
chart = ephemeris.compute_chart(m.julian_day_ut, 44.7866, 20.4489)
tree = dasha.compute(chart.get("Moon").longitude, m.julian_day_ut, levels=2)
tl = transits.timeline(chart, tree, Y0, Y1,
                       bodies=["Jupiter", "Saturn", "Mars", "Rahu"])
ing = [e for e in tl if e.kind == "ingress"]
check("every ingress carries a house number", all(1 <= e.house <= 12 for e in ing))
ok = all(e.house == ((e.sign_index - chart.lagna_sign_index) % 12) + 1 for e in ing)
check("house is correct for this lagna", ok,
      f"lagna {chart.ascendant.sign_english}")

print()
print("=" * 72)
print("8. The timeline is ordered and mixes all event kinds")
check("sorted by time", all(a.jd <= b.jd for a, b in zip(tl, tl[1:])))
kinds = {e.kind for e in tl}
check("contains ingresses, stations and dasha changes",
      kinds == {"ingress", "station", "dasha"}, f"{sorted(kinds)}")

print()
print("=" * 72)
print("2024 for this nativity, slow-moving grahas only:")
for e in tl:
    print("  ", e)

print()
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
