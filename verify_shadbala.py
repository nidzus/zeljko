"""Checks on the numeric strength components.

Each component has a defined maximum and minimum, so the tests place a graha
at those exact points and check the number that comes back.
"""
import sys
sys.path.insert(0, ".")

from backend import ephemeris, shadbala, strength, timeplace

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
print("1. Uchcha bala peaks at exaltation and vanishes at debilitation")
for body, (sign, degree) in strength.EXALTATION.items():
    if body in ("Rahu", "Ketu"):
        continue
    exalted = sign * 30 + degree
    debilitated = (exalted + 180) % 360
    top = shadbala.uchcha_bala(body, exalted)
    bottom = shadbala.uchcha_bala(body, debilitated)
    check(f"{body}: 60 at exaltation, 0 at debilitation",
          abs(top - 60) < 1e-9 and abs(bottom) < 1e-9,
          f"{top:.1f} in {ephemeris.SIGNS[sign][1]} at {degree} degrees, "
          f"{bottom:.1f} opposite")
mid = shadbala.uchcha_bala("Sun", (strength.ARIES * 30 + 10 + 90) % 360)
check("and sits halfway at ninety degrees from either", abs(mid - 30) < 1e-6,
      f"{mid:.1f}")

print()
print("=" * 72)
print("2. Naisargika bala is the fixed natural order")
values = {b: shadbala.naisargika_bala(b) for b in shadbala.NAISARGIKA_RANK}
check("the Sun is strongest at 60", abs(values["Sun"] - 60) < 1e-9)
check("Saturn is weakest", values["Saturn"] == min(values.values()),
      f"{values['Saturn']:.2f}")
check("each is an exact seventh of the way down",
      all(abs(v - 60 * shadbala.NAISARGIKA_RANK[b] / 7) < 1e-9
          for b, v in values.items()),
      " > ".join(f"{b} {v:.1f}" for b, v in
                 sorted(values.items(), key=lambda kv: -kv[1])))

print()
print("=" * 72)
print("3. Dig bala uses the true angles, not the ascendant plus ninety")
print("   The midheaven is not square to the ascendant at most latitudes,")
print("   and using a right angle would put the strong point in the wrong")
print("   place -- here by four and a half degrees.")
gap = (chart.ascendant.longitude - chart.midheaven) % 360
check("the two angles are not ninety degrees apart", abs(gap - 90) > 1.0,
      f"{gap:.2f} degrees between them")
for body, direction, point in [
        ("Jupiter", "ascendant", chart.ascendant.longitude),
        ("Sun", "midheaven", chart.midheaven),
        ("Saturn", "descendant", (chart.ascendant.longitude + 180) % 360),
        ("Moon", "nadir", (chart.midheaven + 180) % 360)]:
    top = shadbala.dig_bala(body, point, chart)
    bottom = shadbala.dig_bala(body, (point + 180) % 360, chart)
    check(f"{body} is strongest at the {direction}",
          abs(top - 60) < 1e-6 and abs(bottom) < 1e-6,
          f"{top:.1f} there, {bottom:.1f} opposite")

print()
print("=" * 72)
print("4. Paksha bala follows the Moon's phase, and reverses for malefics")
full = ephemeris.compute_chart(m.julian_day_ut, *BG)
# Place the Moon opposite the Sun to simulate a full moon, and conjunct it
# for a new moon, without disturbing anything else.
sun_lon = full.get("Sun").longitude
for label, moon_lon, expect_benefic in [("full moon", (sun_lon + 180) % 360, 60),
                                        ("new moon", sun_lon, 0)]:
    full.get("Moon").longitude = moon_lon
    ben = shadbala.paksha_bala("Jupiter", full)
    mal = shadbala.paksha_bala("Saturn", full)
    check(f"at {label}, benefics get {expect_benefic}",
          abs(ben - expect_benefic) < 1e-6, f"Jupiter {ben:.1f}")
    check(f"and malefics get the complement",
          abs(ben + mal - 60) < 1e-6, f"Saturn {mal:.1f}, sum {ben + mal:.1f}")
chart = ephemeris.compute_chart(m.julian_day_ut, *BG)   # restore

print()
print("=" * 72)
print("5. Nathonnatha bala splits day from night")
check("Mercury is always 60, whatever the hour",
      all(shadbala.nathonnatha_bala("Mercury", h) == 60 for h in range(0, 24)))
noon_sun = shadbala.nathonnatha_bala("Sun", 12.0)
midnight_sun = shadbala.nathonnatha_bala("Sun", 0.0)
check("the Sun is strongest at noon, weakest at midnight",
      abs(noon_sun - 60) < 1e-6 and abs(midnight_sun) < 1e-6,
      f"noon {noon_sun:.1f}, midnight {midnight_sun:.1f}")
noon_saturn = shadbala.nathonnatha_bala("Saturn", 12.0)
midnight_saturn = shadbala.nathonnatha_bala("Saturn", 0.0)
check("and Saturn is the exact reverse",
      abs(noon_saturn) < 1e-6 and abs(midnight_saturn - 60) < 1e-6,
      f"noon {noon_saturn:.1f}, midnight {midnight_saturn:.1f}")

print()
print("=" * 72)
print("6. The totals add up and convert correctly")
report = shadbala.assess(chart, birth_hour=16.5)
for entry in report["ranked"]:
    parts = sum(entry["components_virupas"].values())
    if abs(parts - entry["total_virupas"]) > 0.2:
        check(f"{entry['body']} components sum to its total", False,
              f"{parts} vs {entry['total_virupas']}")
        break
else:
    check("every graha's components sum to its total", True)
first = report["ranked"][0]
check("rupas are virupas over sixty",
      abs(first["rupas"] - first["total_virupas"] / 60) < 0.01,
      f"{first['total_virupas']} virupas = {first['rupas']} rupas")
check("all seven grahas are ranked", len(report["ranked"]) == 7)
check("ordered strongest first",
      [e["total_virupas"] for e in report["ranked"]]
      == sorted((e["total_virupas"] for e in report["ranked"]), reverse=True))
check("strongest and weakest are named",
      report["strongest"] == report["ranked"][0]["body"]
      and report["weakest"] == report["ranked"][-1]["body"],
      f"{report['strongest']} strongest, {report['weakest']} weakest")

print()
print("=" * 72)
print("7. It says what it leaves out")
check("the omitted components are listed", len(report["components_omitted"]) >= 6,
      ", ".join(report["components_omitted"]))
check("and it warns against comparing to classical minimums",
      "minimum strengths" in report["caveat"])
check("included and omitted do not overlap",
      not set(report["components_included"]) & set(report["components_omitted"]))

print()
print("=" * 72)
print("Strength ranking for the reference chart:")
for e in report["ranked"]:
    c = e["components_virupas"]
    print(f"  {e['body']:<8} {e['rupas']:>5.2f} rupas   "
          f"uchcha {c['uchcha']:>5.1f}  dig {c['dig']:>5.1f}  "
          f"nais {c['naisargika']:>5.1f}  paksha {c['paksha']:>5.1f}  "
          f"nath {c['nathonnatha']:>5.1f}")

print()
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
