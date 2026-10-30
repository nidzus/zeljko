"""Checks on the Vimshottari engine."""
import sys; sys.path.insert(0, ".")
from backend import timeplace, ephemeris, dasha

results = []


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


m = timeplace.resolve(1988, 3, 12, 16, 30, 44.7866, 20.4489)
chart = ephemeris.compute_chart(m.julian_day_ut, 44.7866, 20.4489)
moon = chart.get("Moon")
tree = dasha.compute(moon.longitude, m.julian_day_ut, levels=3)

print("=" * 72)
print(f"Reference: Moon at {ephemeris.dms(moon.degrees_in_sign)} {moon.sign}, "
      f"{moon.nakshatra} pada {moon.pada}")
print(f"Birth mahadasha balance: {tree.balance_years:.4f} years")
print()

print("=" * 72)
print("1. The cycle sums to exactly 120 years")
total = sum(p.length_days for p in tree.periods[:9]) / dasha.GREGORIAN_YEAR
check("nine mahadashas = 120 years", abs(total - 120) < 1e-9, f"{total:.10f} years")

print()
print("=" * 72)
print("2. Sub-periods exactly fill their parent -- no gaps, no overlaps")
gaps = []
def walk(periods):
    for p in periods:
        if p.children:
            if abs(p.children[0].start_jd - p.start_jd) > 1e-9:
                gaps.append(f"{p.lord} L{p.level}: first child starts late")
            if abs(p.children[-1].end_jd - p.end_jd) > 1e-9:
                gaps.append(f"{p.lord} L{p.level}: last child ends early")
            for a, b in zip(p.children, p.children[1:]):
                if abs(a.end_jd - b.start_jd) > 1e-9:
                    gaps.append(f"{p.lord} L{p.level}: gap at {a.lord}->{b.lord}")
            walk(p.children)
walk(tree.periods)
check("every level is contiguous", not gaps, f"{len(gaps)} discontinuities found")

print()
print("=" * 72)
print("3. Antardasha lengths match the classical ratios")
print("   A sub-period takes lord_years/120 of its parent. These are exact.")
maha = {p.lord: p for p in tree.periods[:9]}
for parent, child, expected in [
    ("Venus", "Venus", 20 * 20 / 120),
    ("Venus", "Sun", 20 * 6 / 120),
    ("Sun", "Sun", 6 * 6 / 120),
    ("Saturn", "Saturn", 19 * 19 / 120),
    ("Moon", "Jupiter", 10 * 16 / 120),
]:
    c = next(x for x in maha[parent].children if x.lord == child)
    got = c.length_days / dasha.GREGORIAN_YEAR
    check(f"{parent} mahadasha / {child} antardasha",
          abs(got - expected) < 1e-6, f"{got:.6f} years, expected {expected:.6f}")

print()
print("=" * 72)
print("4. Against classical tables, which assume a 360-day year")
print("   Published value for Sun antardasha in Sun mahadasha: 3 months 18 days")
sav = dasha.compute(moon.longitude, m.julian_day_ut, levels=2,
                    year_days=dasha.SAVANA_YEAR)
sun_maha = next(p for p in sav.periods[:9] if p.lord == "Sun")
sun_sun = next(c for c in sun_maha.children if c.lord == "Sun")
days = sun_sun.length_days
check("Sun/Sun = 108 days (3 x 30 + 18)", abs(days - 108) < 1e-6, f"{days:.6f} days")

print()
print("=" * 72)
print("5. The mahadasha running at birth is the one the Moon's nakshatra names")
nak_lord = dasha.VIMSHOTTARI[int(moon.longitude // dasha.NAK_ARC) % 9][0]
chain = tree.at(m.julian_day_ut)
check("birth mahadasha lord matches nakshatra lord",
      chain and chain[0].lord == nak_lord,
      f"nakshatra {moon.nakshatra} -> {nak_lord}; running: {tree.describe(m.julian_day_ut)}")
check("three levels resolve at birth", len(chain) == 3)

print()
print("=" * 72)
print("6. The balance is the unelapsed part of the birth mahadasha")
birth_maha = chain[0]
remaining = (birth_maha.end_jd - m.julian_day_ut) / dasha.GREGORIAN_YEAR
check("balance matches the tree", abs(remaining - tree.balance_years) < 1e-6,
      f"{remaining:.6f} vs {tree.balance_years:.6f} years")

print()
print("=" * 72)
print("7. Lookup is continuous across a period boundary")
boundary = tree.periods[0].end_jd
before, after = tree.describe(boundary - 0.5), tree.describe(boundary + 0.5)
check("lookup resolves on both sides", before != after and "outside" not in before,
      f"before: {before}\n       after:  {after}")

print()
print("=" * 72)
print("Dasha sequence from birth:")
for p in tree.periods[:6]:
    running = " <-- at birth" if p.contains(m.julian_day_ut) else ""
    print(f"  {p}{running}")

print()
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
