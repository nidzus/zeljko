"""Checks on Sade Sati and the Moon-relative Saturn periods."""
import sys
sys.path.insert(0, ".")

import swisseph as swe

from backend import ephemeris, shani, timeplace

results = []
BG = (44.7866, 20.4489)
NOW = swe.julday(2026, 8, 28, 0.0)


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
moon_sign = chart.get("Moon").sign_index
state = shani.status(chart, NOW)

print("=" * 72)
print("1. It is measured from the Moon, not the ascendant")
check("both frames are reported, and they differ here",
      state["house_from_moon"] != state["house_from_ascendant"],
      f"Saturn is the {state['house_from_moon']}th from the Moon but the "
      f"{state['house_from_ascendant']}th from the ascendant")
check("the note says which one governs",
      "counted from the Moon" in state["note"])

print()
print("=" * 72)
print("2. Sade Sati runs the classical seven and a half years, not less")
print("   Three signs at about 2.5 years each, stretched by retrogression.")
past = state["last_sade_sati"]
check("the last one lasted between 7 and 9 years",
      7.0 <= past["years"] <= 9.0,
      f"{past['from']} to {past['to']} -- {past['years']} years")
check("it is not truncated to a retrograde re-entry",
      past["from"] < "2015-06-01",
      "chasing ingresses would have reported mid-2017 and lost two years")

print()
print("=" * 72)
print("2b. A past period does not move when the question is asked later")
print("   status() scans a window around the query date. A period already")
print("   under way when that window opens must still report its real start,")
print("   not the window's edge -- otherwise the answer tracks the asker.")
# Needs a chart whose PREVIOUS Sade Sati is long past, so that the scan
# window really does open in the middle of it. A 2010 birth with the Moon in
# Aquarius has one running 1990-1998, which is exactly that case.
m_late = timeplace.resolve(2010, 5, 7, 14, 20, *BG)
chart_late = ephemeris.compute_chart(m_late.julian_day_ut, *BG)

seen = []
for years_on in (0, 3, 6, 9):
    got = shani.status(chart_late, NOW + years_on * 365.2425).get("last_sade_sati")
    if got:
        seen.append((years_on, got["from"], got["to"], got["years"]))

# Asking from further away may legitimately reach a LATER period, once the
# one that was running has ended. What must never happen is the same period
# reporting a different start depending on when it was asked about.
starts_by_end = {}
for _, frm, to, _yrs in seen:
    starts_by_end.setdefault(to, set()).add(frm)
drifting = {to: s for to, s in starts_by_end.items() if len(s) > 1}
check("the same period keeps the same start from every query date",
      not drifting,
      "; ".join(f"ending {to} reported as starting {sorted(s)}"
                for to, s in drifting.items())
      or f"{len(starts_by_end)} period(s) seen, each with one start")
short = [(y, f, t, v) for y, f, t, v in seen if not 7.0 <= v <= 9.0]
check("and every span reported is a full Sade Sati, not a clipped one",
      not short,
      "; ".join(f"+{y}y gave {f}..{t} = {v}y" for y, f, t, v in short)
      or f"spans: {', '.join(f'{v}y' for _, _, _, v in seen)}")

print()
print("=" * 72)
print("3. The boundaries land where Saturn crosses in and out of the block")
block = {(moon_sign + off - 1) % 12 for off in (12, 1, 2)}
start_jd = swe.julday(*[int(x) for x in past["from"].split("-")], 12.0)
end_jd = swe.julday(*[int(x) for x in past["to"].split("-")], 12.0)
check("Saturn is outside the block just before it starts",
      shani._saturn_sign(start_jd - 10) not in block,
      f"before: {ephemeris.SIGNS[shani._saturn_sign(start_jd - 10)][1]}")
check("and inside just after",
      shani._saturn_sign(start_jd + 10) in block,
      f"after: {ephemeris.SIGNS[shani._saturn_sign(start_jd + 10)][1]}")
check("Saturn has left the block just after it ends",
      shani._saturn_sign(end_jd + 10) not in block,
      f"after: {ephemeris.SIGNS[shani._saturn_sign(end_jd + 10)][1]}")

print()
print("=" * 72)
print("4. The phases tile the period without overlapping")
phases = past["phases"]
check("phases are in order and do not overlap",
      all(a["to"] <= b["from"] for a, b in zip(phases, phases[1:])),
      "; ".join(f"{p['phase']} {p['from']}" for p in phases[:3]))
check("the first phase opens the period", phases[0]["from"] == past["from"])
check("the last phase closes it", phases[-1]["to"] == past["to"])
check("all three phases appear",
      {p["phase"].split(" (")[0] for p in phases} == {"rising", "peak", "setting"},
      ", ".join(p["phase"] for p in phases))

print()
print("=" * 72)
print("5. A retrograde return is shown, not smoothed away")
returns = [p for p in phases if "returned" in p["phase"]]
check("Saturn's re-entries are visible", len(returns) > 0,
      "; ".join(f"{p['phase']} {p['sign']} {p['from']} to {p['to']}"
                for p in returns))

print()
print("=" * 72)
print("6. The cycle repeats on Saturn's orbit, about 29.5 years")
nxt = state["next_sade_sati"]
gap = (swe.julday(*[int(x) for x in nxt["from"].split("-")], 12.0)
       - start_jd) / 365.2425
check("consecutive Sade Satis are about 29 years apart",
      28.0 <= gap <= 31.0, f"{past['from']} to {nxt['from']} = {gap:.1f} years")

print()
print("=" * 72)
print("7. The smaller Saturn periods are found too")
running = state["running"]
check("something is running now", running is not None,
      f"{running['kind']} from {running['from']} to {running['to']}"
      if running else "nothing")
check("it is the 4th from the Moon, which is Kantaka Shani",
      running and running["kind"] == "Kantaka Shani"
      and state["house_from_moon"] == 4)
check("with how far through it is",
      0.0 <= running["elapsed_fraction"] <= 1.0,
      f"{running['elapsed_fraction']:.0%} elapsed, "
      f"{running['remaining_years']} years left")

print()
print("=" * 72)
print("8. A chart whose Moon sits elsewhere gets a different answer")
print("   Same moment in the sky, different natal Moon -- so a different")
print("   period, which is the entire reason this is computed from the Moon.")
other = timeplace.resolve(1990, 7, 4, 9, 15, 48.2082, 16.3738)
other_chart = ephemeris.compute_chart(other.julian_day_ut, 48.2082, 16.3738)
other_state = shani.status(other_chart, NOW)
check("the two charts read differently",
      other_state["house_from_moon"] != state["house_from_moon"],
      f"Moon in {state['natal_moon_sign']} -> "
      f"{state['house_from_moon']}th; Moon in "
      f"{other_state['natal_moon_sign']} -> "
      f"{other_state['house_from_moon']}th")
check("and the transiting sign is of course the same for both",
      other_state["saturn_transiting"] == state["saturn_transiting"],
      f"Saturn is in {state['saturn_transiting']} either way")

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
