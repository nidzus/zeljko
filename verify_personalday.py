"""Checks on Tara bala and Chandra bala."""
import sys
sys.path.insert(0, ".")

import swisseph as swe

from backend import ephemeris, personalday, timeplace, transits

results = []
BG = (44.7866, 20.4489)
NOW = swe.julday(2026, 8, 28, 6.0)


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
natal_moon = chart.get("Moon")

print("=" * 72)
print("1. The nine Taras are named and classified as tradition has them")
check("nine of them", len(personalday.TARAS) == 9)
favourable = [t[0] for t in personalday.TARAS if t[2]]
check("five are favourable",
      favourable == ["Sampat", "Kshema", "Sadhaka", "Mitra", "Ati Mitra"],
      ", ".join(favourable))
unfavourable = [t[0] for t in personalday.TARAS if not t[2]]
check("four are not",
      unfavourable == ["Janma", "Vipat", "Pratyari", "Vadha"],
      ", ".join(unfavourable))

print()
print("=" * 72)
print("2. Janma tara falls when the Moon returns to your birth star")
print("   The Moon crosses the natal nakshatra roughly every 27 days.")
found = None
for offset in range(30):
    jd = NOW + offset
    if int(transits.state(jd, "Moon")[0] // (360 / 27)) == natal_moon.nakshatra_index:
        found = jd
        break
check("the natal nakshatra recurs within a month", found is not None)
day = personalday.at(chart, found)
check("and it reads as Janma", day.tara == "Janma",
      f"{day.moon_nakshatra} -- natal star is {natal_moon.nakshatra}")
check("with the divided opinion stated rather than resolved",
      "divides" in day.note)

print()
print("=" * 72)
print("3. Chandra bala is the Moon's sign from the natal Moon's")
target = None
for offset in range(30):
    jd = NOW + offset
    if int(transits.state(jd, "Moon")[0] // 30) == natal_moon.sign_index:
        target = jd
        break
d = personalday.at(chart, target)
check("the Moon in your natal sign is the 1st", d.chandra_house == 1,
      f"Moon back in {natal_moon.sign_english}")
houses = {personalday.at(chart, NOW + o).chandra_house for o in range(30)}
check("all twelve are reachable across a month", len(houses) == 12,
      f"{len(houses)} distinct houses seen")

print()
print("=" * 72)
print("4. All nine Taras appear over a full lunar circuit")
taras = [personalday.at(chart, NOW + o).tara for o in range(28)]
check("every Tara occurs", len(set(taras)) == 9,
      f"{len(set(taras))} distinct across 28 days")
cycles = {personalday.at(chart, NOW + o).cycle for o in range(28)}
check("and all three cycles are distinguished", cycles == {1, 2, 3},
      f"cycles seen: {sorted(cycles)}")

print()
print("=" * 72)
print("5. The Tara changes when the Moon changes nakshatra, not at midnight")
day = personalday.at(chart, NOW)
change_jd = personalday._changes_at(NOW, natal_moon.nakshatra_index, "LAHIRI")
before = int(transits.state(change_jd - 3 / 1440, "Moon")[0] // (360 / 27))
after = int(transits.state(change_jd + 3 / 1440, "Moon")[0] // (360 / 27))
check("the Moon's nakshatra changes at the stated moment", before != after,
      f"{day.tara_changes_at}: nakshatra {before} -> {after}")
check("which is not midnight", not day.tara_changes_at.endswith("00:00 UT"),
      "a calendar day can carry two Taras, which is why the time is given")

print()
print("=" * 72)
print("6. Two charts read the same day differently")
print("   This is the whole point: the panchanga cannot do this.")
other_m = timeplace.resolve(1990, 7, 4, 9, 15, 48.2082, 16.3738)
other = ephemeris.compute_chart(other_m.julian_day_ut, 48.2082, 16.3738)
differ = 0
for offset in range(14):
    jd = NOW + offset
    a, b = personalday.at(chart, jd), personalday.at(other, jd)
    if a.verdict != b.verdict:
        differ += 1
check("their verdicts diverge across a fortnight", differ > 0,
      f"{differ} of 14 days read differently")
a, b = personalday.at(chart, NOW), personalday.at(other, NOW)
check("on the same Moon nakshatra", a.moon_nakshatra == b.moon_nakshatra,
      f"both see {a.moon_nakshatra}, but chart A gets {a.tara} and "
      f"chart B gets {b.tara}")

print()
print("=" * 72)
print("7. A window can be searched, not just described")
w = personalday.window(chart, NOW, days=14)
check("fourteen days returned", len(w) == 14)
check("each carries a verdict",
      all(d["verdict"] in ("favourable", "mixed", "poor") for d in w))
best = personalday.best_days(chart, NOW, days=30)
check("favourable days can be picked out of a month", len(best) > 0,
      ", ".join(d["date"] for d in best[:6]))
check("and they are a subset, not everything", len(best) < 30,
      f"{len(best)} of 30 days")

print()
print("=" * 72)
print("8. It qualifies an answer rather than replacing one")
check("every reading says so", all("does not make one" in
      personalday.at(chart, NOW + o).note for o in range(5)))

print()
print("=" * 72)
print("Next fortnight for this chart:")
for d in w:
    t = d["tara"]
    print(f"  {d['date']}  {t['name']:<10} cycle {t['cycle']}  "
          f"{d['chandra_bala']['house_from_natal_moon']:>2}th  {d['verdict']}")

print()
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
