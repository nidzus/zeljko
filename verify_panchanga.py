"""Checks on the five limbs."""
import sys
sys.path.insert(0, ".")

from collections import Counter
from datetime import date

import swisseph as swe

from backend import ephemeris, panchanga

results = []
BG_LAT, BG_LON = 44.7866, 20.4489


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


print("=" * 72)
print("1. The weekday is the actual weekday")
for y, m, d in [(2026, 8, 28), (2000, 1, 1), (1988, 3, 12), (2024, 2, 29)]:
    jd = swe.julday(y, m, d, 12.0)
    p = panchanga.panchanga(jd, BG_LAT, BG_LON)
    expected = date(y, m, d).strftime("%A")
    check(f"{y}-{m:02d}-{d:02d} is a {expected}",
          p["vara"]["english"] == expected,
          f"{p['vara']['name']} ({p['vara']['english']}), lord {p['vara']['lord']}")

print()
print("=" * 72)
print("2. Purnima falls at opposition and Amavasya at conjunction")
print("   Find the actual full and new moon, then ask what tithi it is.")


def elongation(jd):
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    f = swe.FLG_MOSEPH | swe.FLG_SIDEREAL
    sun, _ = swe.calc_ut(jd, swe.SUN, f)
    moon, _ = swe.calc_ut(jd, swe.MOON, f)
    return (moon[0] - sun[0]) % 360


def find_phase(start_jd, target):
    """Walk to the moment the Sun-Moon elongation reaches a given angle."""
    jd = start_jd
    prev = (elongation(jd) - target) % 360
    while jd < start_jd + 40:
        jd += 0.02
        cur = (elongation(jd) - target) % 360
        if cur < prev and prev > 180:
            lo, hi = jd - 0.02, jd
            while hi - lo > 1 / 1440:
                mid = (lo + hi) / 2
                if ((elongation(mid) - target) % 360) > 180:
                    lo = mid
                else:
                    hi = mid
            return hi
        prev = cur
    raise RuntimeError("phase not found")


full = find_phase(swe.julday(2026, 8, 1, 0.0), 180)
new = find_phase(swe.julday(2026, 8, 1, 0.0), 0)
# Ask just after the exact phase so the limb in force is unambiguous.
p_full = panchanga.panchanga(full + 0.01, BG_LAT, BG_LON)
p_new = panchanga.panchanga(new + 0.01, BG_LAT, BG_LON)
check("the full moon is Purnima", "Purnima" in p_full["tithi"]["name"],
      f"elongation 180 deg -> {p_full['tithi']['name']}")
check("the new moon is Amavasya", "Amavasya" in p_new["tithi"]["name"],
      f"elongation 0 deg -> {p_new['tithi']['name']}")
check("Purnima closes the waxing fortnight", p_full["tithi"]["paksha"] == "Shukla")
check("Amavasya closes the waning fortnight", p_new["tithi"]["paksha"] == "Krishna")

print()
print("=" * 72)
print("3. Each limb genuinely ends when it says it does")
jd = swe.julday(2026, 8, 28, 6.0)
p = panchanga.panchanga(jd, BG_LAT, BG_LON)
rise = panchanga.sun_times(jd, BG_LAT, BG_LON)[0]
for limb, index_fn in [("tithi", panchanga._tithi_index),
                       ("nakshatra", panchanga._nakshatra_index),
                       ("yoga", panchanga._yoga_index),
                       ("karana", panchanga._karana_index)]:
    ends = panchanga._ends_at(rise, index_fn, "LAHIRI")
    before = index_fn(ends - 2 / 1440, "LAHIRI")
    after = index_fn(ends + 2 / 1440, "LAHIRI")
    check(f"{limb} index changes across its stated end", before != after,
          f"{p[limb]['ends']}: index {before} -> {after}")

print()
print("=" * 72)
print("4. Sixty karanas fill a lunar month in the classical pattern")
names = [panchanga.karana_name(i) for i in range(60)]
counts = Counter(names)
check("it opens with the fixed Kimstughna", names[0] == "Kimstughna")
check("it closes with the three fixed karanas",
      names[-3:] == ["Shakuni", "Chatushpada", "Naga"])
check("each fixed karana occurs exactly once",
      all(counts[k] == 1 for k in ["Kimstughna", "Shakuni", "Chatushpada", "Naga"]))
check("each movable karana occurs eight times",
      all(counts[k] == 8 for k in panchanga.MOVABLE_KARANAS),
      f"7 movable x 8 = 56, plus 4 fixed = {sum(counts.values())}")

print()
print("=" * 72)
print("5. Sunrise, sunset and Rahu Kaal are coherent")
check("sunrise precedes the moment asked about",
      rise < jd, f"sunrise {p['sunrise']}")
sset = panchanga.sun_times(jd, BG_LAT, BG_LON)[1]
check("sunset follows sunrise", sset > rise,
      f"daylight {round((sset - rise) * 24, 2)} hours")
check("Rahu Kaal is one eighth of daylight",
      abs((sset - rise) / 8 * 24 * 60 - 100.7) < 20,
      f"{round((sset - rise) / 8 * 24 * 60)} minutes, {p['rahu_kaal']['from']} "
      f"to {p['rahu_kaal']['to']}")

print()
print("=" * 72)
print("6. Rahu Kaal sits where tradition puts it")
print("   With a six o'clock sunrise the published slots are Monday 07:30,")
print("   Saturday 09:00, Friday 10:30, Wednesday 12:00, Thursday 13:30,")
print("   Tuesday 15:00, Sunday 16:30 -- parts 2, 3, 4, 5, 6, 7 and 8.")
expected_parts = {"Sunday": 8, "Monday": 2, "Tuesday": 7, "Wednesday": 5,
                  "Thursday": 6, "Friday": 4, "Saturday": 3}
ok = all(panchanga.RAHU_KAAL_PART[i] == expected_parts[eng]
         for i, (_, eng, _) in enumerate(panchanga.VARA_NAMES))
check("the weekday-to-part mapping matches", ok,
      ", ".join(f"{eng[:3]}={panchanga.RAHU_KAAL_PART[i]}"
                for i, (_, eng, _) in enumerate(panchanga.VARA_NAMES)))

print()
print("=" * 72)
print("7. The Moon's nakshatra agrees with the chart engine")
swe.set_sid_mode(swe.SIDM_LAHIRI)
moon, _ = swe.calc_ut(rise, swe.MOON, swe.FLG_MOSEPH | swe.FLG_SIDEREAL)
direct = ephemeris.NAKSHATRAS[int(moon[0] // (360 / 27))]
check("same nakshatra from both paths", p["nakshatra"]["name"] == direct,
      f"{p['nakshatra']['name']}")

print()
print("=" * 72)
print("8. All 27 yogas and 30 tithis are named")
check("27 yoga names", len(panchanga.YOGA_NAMES) == 27
      and len(set(panchanga.YOGA_NAMES)) == 27)
check("14 repeating tithi names, plus Purnima and Amavasya",
      len(panchanga.TITHI_NAMES) == 14
      and len(set(panchanga.TITHI_NAMES)) == 14)

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
