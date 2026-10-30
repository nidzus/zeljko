"""How much birth-time error can each part of the app tolerate?

Answers a practical question: if the birth time is off by N minutes, which
conclusions change and which hold? Run it for any chart to see where that
chart's own fragile boundaries are.
"""
import sys; sys.path.insert(0, ".")
from backend import timeplace, ephemeris

LAT, LON, TZ = 44.7866, 20.4489, "Belgrade"
Y, M, D, HH, MM = 1988, 3, 12, 16, 30

# Vimshottari: the 120-year cycle, in nakshatra order from Ashwini.
LORDS = [("Ketu", 7), ("Venus", 20), ("Sun", 6), ("Moon", 10), ("Mars", 7),
         ("Rahu", 18), ("Jupiter", 16), ("Saturn", 19), ("Mercury", 17)]
NAK_ARC = 360.0 / 27


def snapshot(offset_minutes):
    total = HH * 60 + MM + offset_minutes
    m = timeplace.resolve(Y, M, D, total // 60, total % 60, LAT, LON)
    c = ephemeris.compute_chart(m.julian_day_ut, LAT, LON)

    moon = c.get("Moon").longitude
    # Navamsa: each sign split into nine parts of 3 deg 20'.
    d9_lagna = int(c.ascendant.longitude / (30 / 9)) % 12
    # D-60: each sign split into sixty parts of 0 deg 30'.
    d60_lagna = int(c.ascendant.longitude / 0.5) % 12

    nak = int(moon // NAK_ARC)
    elapsed = (moon % NAK_ARC) / NAK_ARC
    lord, years = LORDS[nak % 9]
    balance = (1 - elapsed) * years          # years of the birth dasha left

    return {
        "lagna": c.ascendant.sign_english,
        "lagna_deg": c.ascendant.longitude,
        "d9": ephemeris.SIGNS[d9_lagna][1],
        "d60": ephemeris.SIGNS[d60_lagna][1],
        "nak": ephemeris.NAKSHATRAS[nak],
        "lord": lord,
        "balance": balance,
    }


base = snapshot(0)
print(f"Reference chart: {Y}-{M:02d}-{D:02d} {HH}:{MM:02d}, {TZ}")
print(f"  rasi lagna {base['lagna']}   navamsa lagna {base['d9']}   "
      f"D-60 lagna {base['d60']}")
print(f"  Moon in {base['nak']}, dasha of {base['lord']}, "
      f"{base['balance']:.3f} years remaining at birth")
print()
print(f"{'error':>8} | {'rasi':<10} {'D-9':<10} {'D-60':<10} {'nakshatra':<12} "
      f"{'dasha dates shift by':>22}")
print("-" * 88)

for off in (-60, -30, -15, -10, -5, -2, -1, 1, 2, 5, 10, 15, 30, 60):
    s = snapshot(off)
    shift_days = abs(s["balance"] - base["balance"]) * 365.25
    mark = lambda a, b: f"{a}" if a == b else f"{a} *"
    if shift_days < 1:
        shift = f"{shift_days*24:.1f} hours"
    elif shift_days < 60:
        shift = f"{shift_days:.1f} days"
    else:
        shift = f"{shift_days/30.44:.1f} months"
    print(f"{off:+5d} min | {mark(s['lagna'], base['lagna']):<10} "
          f"{mark(s['d9'], base['d9']):<10} {mark(s['d60'], base['d60']):<10} "
          f"{mark(s['nak'], base['nak']):<12} {shift:>22}")

print()
print("* = differs from the reference chart")
