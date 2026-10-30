"""Checks that the reliability gate is honest and chart-specific."""
import sys; sys.path.insert(0, ".")
from datetime import datetime, timedelta

from backend import ephemeris, timeplace
from backend.confidence import assess, TimeConfidence

BELGRADE = (44.7866, 20.4489)
CLAIMS = ("house_placement", "dasha_lord", "dasha_date", "navamsa", "shashtiamsa")
results = []


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


print("=" * 72)
print("1. Wider uncertainty never permits more than narrower uncertainty")
levels = list(TimeConfidence)
allowed = []
for c in levels:
    r = assess(1988, 3, 12, 16, 30, *BELGRADE, c)
    allowed.append({x for x in CLAIMS if r.allows(x)})
monotone = all(allowed[i + 1] <= allowed[i] for i in range(len(allowed) - 1))
check("permissions shrink monotonically", monotone,
      " -> ".join(f"{c.name}:{len(a)}" for c, a in zip(levels, allowed)))

print()
print("=" * 72)
print("2. A birth time known only as a family story supports nothing")
r = assess(1988, 3, 12, 16, 30, *BELGRADE, TimeConfidence.VAGUE)
check("VAGUE refuses every claim", not any(r.allows(x) for x in CLAIMS))
check("and states no dasha dates", r.date_precision == "none")

print()
print("=" * 72)
print("3. Dasha drift grows with the uncertainty window")
drifts = [assess(1988, 3, 12, 16, 30, *BELGRADE, c).dasha_drift_days
          for c in levels]
check("drift is non-decreasing", all(a <= b for a, b in zip(drifts, drifts[1:])),
      ", ".join(f"{c.name} {d:.1f}d" for c, d in zip(levels, drifts)))

print()
print("=" * 72)
print("4. The gate is chart-specific, not a generic rule")
print("   Find when this chart's lagna crosses a sign boundary, then test a")
print("   birth one minute away from it. Same confidence, opposite verdict.")

base = datetime(1988, 3, 12, 16, 30)
prev_sign, crossing = None, None
for i in range(0, 240):
    t = base + timedelta(minutes=i)
    m = timeplace.resolve(t.year, t.month, t.day, t.hour, t.minute, *BELGRADE)
    sign = int(ephemeris.compute_chart(m.julian_day_ut, *BELGRADE).ascendant.longitude // 30)
    if prev_sign is not None and sign != prev_sign:
        crossing = t
        break
    prev_sign = sign

print(f"   lagna changes sign at about {crossing:%H:%M}")
near = crossing - timedelta(minutes=1)
r_near = assess(near.year, near.month, near.day, near.hour, near.minute,
                *BELGRADE, TimeConfidence.REMEMBERED)
r_mid = assess(1988, 3, 12, 16, 30, *BELGRADE, TimeConfidence.REMEMBERED)
check("mid-sign birth: lagna stable at +/-15 min", r_mid.rasi_lagna_stable,
      f"{r_mid.degrees_to_lagna_boundary:.2f} deg to boundary")
check("boundary birth: lagna NOT stable at the same confidence",
      not r_near.rasi_lagna_stable,
      f"{r_near.degrees_to_lagna_boundary:.2f} deg to boundary")
check("so the boundary birth is refused house claims",
      not r_near.allows("house_placement"))

print()
print("=" * 72)
print("5. An unrecognised claim fails loudly rather than defaulting to allowed")
try:
    r_mid.allows("whatever")
    check("unknown claim rejected", False, "it returned instead of raising")
except KeyError:
    check("unknown claim rejected", True)

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
