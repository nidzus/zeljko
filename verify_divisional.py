"""Checks on the divisional charts.

Each varga has structural properties that a wrong formula breaks, so the tests
lean on those rather than on remembered example charts.
"""
import sys
sys.path.insert(0, ".")

from backend import divisional, ephemeris, timeplace

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


def scan(varga, step=0.05):
    lon = 0.0
    while lon < 360.0:
        yield lon, divisional.varga_sign(lon, varga)
        lon += step


print("=" * 72)
print("1. The sign a body starts in must affect the answer")
print("   This is the bug that was there: for the D-60 the rasi cancelled out")
print("   and all twelve signs gave the same result.")
for varga in sorted(divisional.VARGAS):
    if varga in (1, 2):
        continue
    seen = {divisional.varga_sign(rasi * 30 + 7.0, varga) for rasi in range(12)}
    check(f"D-{varga}: same degree in twelve signs gives varied results",
          len(seen) > 1, f"{len(seen)} distinct")

print()
print("=" * 72)
print("2. Every equal-division varga reaches all twelve signs")
for varga in (3, 4, 7, 9, 10, 12, 60):
    signs = {s for _, s in scan(varga)}
    check(f"D-{varga} covers the zodiac", len(signs) == 12,
          f"{len(signs)} signs reached")

print()
print("=" * 72)
print("3. The hora yields only Cancer or Leo")
hora = {s for _, s in scan(2)}
check("nothing but the Sun's and Moon's signs",
      hora == {divisional.CANCER, divisional.LEO},
      ", ".join(sorted(ephemeris.SIGNS[s][1] for s in hora)))
check("odd signs open with Leo",
      divisional.varga_sign(0.0, 2) == divisional.LEO,
      "Aries 0 degrees -> Leo")
check("even signs open with Cancer",
      divisional.varga_sign(30.0, 2) == divisional.CANCER,
      "Taurus 0 degrees -> Cancer")

print()
print("=" * 72)
print("4. The trimsamsa never yields Cancer or Leo")
print("   The luminaries own no trimsamsa, so a formula that produces one")
print("   is wrong. This is the property that catches a bad table.")
tri = {s for _, s in scan(30)}
check("neither luminary sign appears",
      divisional.CANCER not in tri and divisional.LEO not in tri,
      f"{len(tri)} signs used: " +
      ", ".join(sorted(ephemeris.SIGNS[s][1] for s in tri)))
check("and the other ten all do", len(tri) == 10)

print()
print("=" * 72)
print("5. Divisions are the right size")
for varga in (3, 4, 7, 9, 10, 12, 60):
    boundaries = 0
    prev = divisional.varga_sign(0.0, varga)
    lon = 0.0
    # Stop short of 30 degrees: at exactly 30 we are in the next sign, and
    # counting that boundary would report one cut too many.
    while lon < 29.99:
        lon += 0.01
        cur = divisional.varga_sign(lon, varga)
        if cur != prev:
            boundaries += 1
            prev = cur
    check(f"D-{varga} makes {varga - 1} cuts inside one sign",
          boundaries == varga - 1, f"{boundaries} found")

print()
print("=" * 72)
print("6. The navamsa still matches the old continuous formula")
print("   That one was right, and must not regress while the others are fixed.")
mismatch = [lon for lon, s in scan(9, 0.37)
            if s != int(lon / (30 / 9)) % 12]
check("navamsa unchanged", not mismatch,
      f"{len(mismatch)} disagreements over the whole zodiac")

print()
print("=" * 72)
print("7. Vargottama means the same sign in both charts")
d9 = divisional.compute(chart, 9)
for entry in d9.positions:
    natal = chart.get(entry["body"])
    expected = entry["sign"] == natal.sign_english
    if entry["vargottama"] != expected:
        check(f"{entry['body']} vargottama flag", False)
        break
else:
    check("every vargottama flag agrees with the two signs", True,
          ", ".join(e["body"] for e in d9.positions if e["vargottama"])
          or "none vargottama in this chart")

print()
print("=" * 72)
print("8. A divisional chart stands on its own lagna")
d10 = divisional.compute(chart, 10)
check("houses run 1 to 12", all(1 <= e["house"] <= 12 for e in d10.positions))
check("its own lagna is the first house",
      all(e["house"] == 1 for e in d10.positions if e["sign"] == d10.lagna),
      f"D-10 lagna is {d10.lagna}")
check("and it need not match the rasi lagna",
      isinstance(d10.lagna, str),
      f"rasi lagna {chart.ascendant.sign_english}, D-10 lagna {d10.lagna}")

print()
print("=" * 72)
print("9. Each varga says what it is read for")
for varga, (name, read_for) in divisional.VARGAS.items():
    if not (name and read_for):
        check(f"D-{varga} described", False)
        break
else:
    check("all ten carry a name and a purpose", True,
          "; ".join(f"D-{v} {n}" for v, (n, _) in
                    list(divisional.VARGAS.items())[:5]) + " ...")
try:
    divisional.varga_sign(10.0, 11)
    check("an unsupported varga is refused", False, "it returned something")
except ValueError:
    check("an unsupported varga is refused", True)

print()
print("=" * 72)
print(f"Career chart (D-10) for the reference nativity, lagna {d10.lagna}:")
for e in d10.positions:
    mark = "  vargottama" if e["vargottama"] else ""
    print(f"  {e['body']:<8} {e['sign']:<12} house {e['house']}{mark}")

print()
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
