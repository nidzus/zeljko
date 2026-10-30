"""Checks on the time-and-place layer -- where charts go wrong invisibly.

Every case here is one that produces a plausible-looking but wrong chart if
mishandled, with nothing to alert you.
"""
import sys; sys.path.insert(0, ".")
from backend import timeplace

BELGRADE = (44.7866, 20.4489)
results = []


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


print("=" * 70)
print("1. Ordinary modern birth -- standard timezone, nothing exotic")
m = timeplace.resolve(1988, 3, 12, 16, 30, *BELGRADE)
check("uses the IANA offset, not local mean time",
      not m.used_local_mean_time,
      f"{m.timezone_name} {m.utc_offset_hours:+.2f}h -> {m.utc}")
check("offset is a whole number of minutes",
      (m.utc_offset_hours * 60) % 1 == 0)

print()
print("=" * 70)
print("2. Summer birth -- DST must be applied for the date, not for today")
s = timeplace.resolve(1988, 7, 12, 16, 30, *BELGRADE)
check("summer offset is one hour ahead of winter",
      abs((s.utc_offset_hours - m.utc_offset_hours) - 1.0) < 1e-9,
      f"winter {m.utc_offset_hours:+.0f}h, summer {s.utc_offset_hours:+.0f}h")

print()
print("=" * 70)
print("3. A local time that happened TWICE (clocks went back)")
print("   Belgrade, 27 Oct 2024: 03:00 became 02:00, so 02:30 occurred twice.")
a = timeplace.resolve(2024, 10, 27, 2, 30, *BELGRADE)
check("flagged as ambiguous", a.ambiguous,
      "the chart is unresolvable without knowing which 02:30 -- must be asked")

print()
print("=" * 70)
print("4. A local time that NEVER happened (clocks went forward)")
print("   Belgrade, 31 Mar 2024: 02:00 became 03:00, so 02:30 does not exist.")
n = timeplace.resolve(2024, 3, 31, 2, 30, *BELGRADE)
check("flagged as nonexistent", n.nonexistent,
      "the birth time as recorded is impossible -- must be queried")

print()
print("=" * 70)
print("5. Birth before standard time existed")
print("   Serbia adopted Central European Time in 1884. Before that, IANA")
print("   reports Belgrade's own mean time -- but for a birth elsewhere in")
print("   the zone it would report the WRONG city's mean time.")
old = timeplace.resolve(1870, 5, 5, 12, 0, *BELGRADE)
check("switched to the birthplace's true local mean time",
      old.used_local_mean_time,
      f"IANA said {old.iana_offset_hours:+.4f}h, we used {old.utc_offset_hours:+.4f}h")
expected_lmt = BELGRADE[1] / 15.0
check("local mean time derived from longitude",
      abs(old.utc_offset_hours - expected_lmt) < 1e-9,
      f"{BELGRADE[1]}E / 15 = {expected_lmt:.4f}h")

print()
print("=" * 70)
print("6. Both offsets are always recorded, so any chart can be audited")
check("iana_offset_hours retained even when overridden",
      old.iana_offset_hours != old.utc_offset_hours)

print()
print("=" * 70)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
