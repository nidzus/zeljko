"""Checks on aspects and yoga detection.

Most cases are built from synthetic charts rather than real birth times: to
test that a Ruchaka yoga is found you need Mars exalted in an angle, and
hunting for a birth moment that produces one is far less clear than simply
placing it there.
"""
import sys
sys.path.insert(0, ".")

from backend import ephemeris, strength, timeplace, yogas

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


def make_chart(lagna_sign: int, placements: dict[str, float],
               park: float = 0.0) -> ephemeris.Chart:
    """Build a chart by hand. Placements are absolute sidereal longitudes.

    Anything unplaced goes to `park`. That matters more than it looks: leaving
    them all at zero degrees Aries can put them somewhere meaningful by
    accident, which is how this helper first produced a Durudhara yoga when the
    test was trying to isolate a Sunapha.
    """
    asc = ephemeris._decompose("Lagna", "Lagna", lagna_sign * 30 + 15, 0.0)
    positions = []
    for name, sanskrit, _code in ephemeris.GRAHAS:
        positions.append(ephemeris._decompose(
            name, sanskrit, placements.get(name, park), 1.0))
    rahu = next(p for p in positions if p.name == "Rahu")
    positions.append(ephemeris._decompose("Ketu", "Ketu",
                                          rahu.longitude + 180, -0.05))
    chart = ephemeris.Chart(
        julian_day_ut=0.0, latitude=0.0, longitude=0.0,
        ayanamsa_name="LAHIRI", ayanamsa_value=0.0,
        ascendant=asc, positions=positions)
    asc.house = 1
    for p in chart.positions:
        p.house = chart.house_of(p.sign_index)
    return chart


def names(chart):
    return {y.name for y in yogas.detect(chart)}


print("=" * 72)
print("1. Aspects follow the classical rules")
check("everything aspects the seventh", yogas.aspect_offsets("Venus") == (7,))
check("Mars adds the fourth and eighth",
      yogas.aspect_offsets("Mars") == (4, 7, 8))
check("Jupiter adds the fifth and ninth",
      yogas.aspect_offsets("Jupiter") == (5, 7, 9))
check("Saturn adds the third and tenth",
      yogas.aspect_offsets("Saturn") == (3, 7, 10))

# Mars in the 5th: the 4th from there is the 8th, the 8th is the 12th.
chart = make_chart(strength.LEO, {"Mars": strength.SAGITTARIUS * 30 + 5})
check("Mars in the 5th aspects the 8th, 11th and 12th",
      yogas.aspected_houses(chart, "Mars") == [8, 11, 12],
      str(yogas.aspected_houses(chart, "Mars")))

print()
print("=" * 72)
print("2. House lordship follows the sign in the house")
chart = make_chart(strength.LEO, {})
check("Leo lagna makes the Sun lord of the 1st",
      yogas.house_lord(chart, 1) == "Sun")
check("and Saturn lord of both the 6th and 7th",
      yogas.houses_ruled(chart, "Saturn") == [6, 7],
      f"Saturn rules {yogas.houses_ruled(chart, 'Saturn')}")

print()
print("=" * 72)
print("3. The five mahapurusha yogas need dignity AND an angle")
for body, name, sign in [("Mars", "Ruchaka", strength.CAPRICORN),
                         ("Mercury", "Bhadra", strength.VIRGO),
                         ("Jupiter", "Hamsa", strength.CANCER),
                         ("Venus", "Malavya", strength.PISCES),
                         ("Saturn", "Sasa", strength.LIBRA)]:
    # Choose a lagna that puts the exaltation sign in an angle (the 4th).
    lagna = (sign - 3) % 12
    c = make_chart(lagna, {body: sign * 30 + 10})
    check(f"{name} yoga from an exalted {body} in an angle",
          f"{name} yoga" in names(c),
          f"{body} exalted in {ephemeris.SIGNS[sign][1]}, "
          f"house {c.get(body).house}")

print()
print("=" * 72)
print("4. Dignity alone is not enough -- it must also be angular")
# Same exalted Mars, but in the 3rd rather than an angle.
c = make_chart((strength.CAPRICORN - 2) % 12,
               {"Mars": strength.CAPRICORN * 30 + 10})
check("an exalted Mars outside an angle gives no Ruchaka",
      "Ruchaka yoga" not in names(c),
      f"Mars exalted but in house {c.get('Mars').house}")

print()
print("=" * 72)
print("5. The Moon yogas depend on what flanks the Moon")
moon = strength.TAURUS * 30 + 10
second, twelfth = strength.GEMINI * 30 + 5, strength.ARIES * 30 + 5
away = strength.SCORPIO * 30 + 15    # opposite the Moon, flanking nothing
c = make_chart(strength.TAURUS, {"Moon": moon, "Venus": second}, park=away)
check("a graha in the 2nd from the Moon gives Sunapha",
      "Sunapha yoga" in names(c))
c = make_chart(strength.TAURUS, {"Moon": moon, "Venus": twelfth}, park=away)
check("a graha in the 12th gives Anapha", "Anapha yoga" in names(c))
c = make_chart(strength.TAURUS,
               {"Moon": moon, "Venus": second, "Mars": twelfth}, park=away)
check("both sides occupied gives Durudhara",
      "Durudhara yoga" in names(c))
check("and the three are mutually exclusive",
      len({"Sunapha yoga", "Anapha yoga", "Durudhara yoga"} & names(c)) == 1)

print()
print("=" * 72)
print("6. Kala Sarpa needs every graha on one side of the nodes")
inside = {"Rahu": 0.0, "Sun": 30.0, "Moon": 60.0, "Mars": 90.0,
          "Mercury": 120.0, "Jupiter": 150.0, "Venus": 170.0, "Saturn": 100.0}
c = make_chart(strength.ARIES, inside)
check("all seven inside the axis is detected",
      "Kala Sarpa yoga" in names(c))
straddling = dict(inside, Saturn=250.0)
c = make_chart(strength.ARIES, straddling)
check("one graha outside breaks it",
      "Kala Sarpa yoga" not in names(c),
      "Saturn moved past Ketu")

print()
print("=" * 72)
print("7. Raja yogas are qualified when a lord also rules a difficult house")
m = timeplace.resolve(1988, 3, 12, 16, 30, *BG)
real = ephemeris.compute_chart(m.julian_day_ut, *BG)
rajas = [y for y in yogas.detect(real) if y.name == "Raja yoga"]
check("the reference chart carries raja yogas", len(rajas) > 0,
      f"{len(rajas)} found")
qualified = [y for y in rajas if y.caveat]
check("those involving a difficult-house lord say so", len(qualified) > 0,
      qualified[0].caveat[:96] if qualified else "none carried a caveat")

print()
print("=" * 72)
print("8. Nothing is claimed without evidence")
every = yogas.detect(real)
check("every finding names what it involves", all(y.involves for y in every))
check("every finding explains itself", all(y.detail for y in every))
check("kinds are from the known set",
      all(y.kind in ("raja", "dhana", "mahapurusha", "lunar", "affliction",
                     "other") for y in every),
      ", ".join(sorted({y.kind for y in every})))
disputed = [y for y in every if y.caveat]
check("disputed readings carry their caveat rather than asserting",
      all("caveat" in y.as_dict() for y in disputed),
      f"{len(disputed)} of {len(every)} findings are qualified")

print()
print("=" * 72)
print("Yogas in the reference chart:")
for y in every:
    print(f"  [{y.kind}] {y.name}: {', '.join(y.involves)}")

print()
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
