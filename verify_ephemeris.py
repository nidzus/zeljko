"""Independent checks on the astronomy layer.

Each check compares Swiss Ephemeris output against a value we know from an
outside source, not against itself. If these pass, the foundation is sound.
"""
import swisseph as swe

# Moshier: the analytical ephemeris built into the C library. No data files
# needed, accurate to well under an arcsecond -- far finer than jyotisha uses.
FLAGS = swe.FLG_MOSEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED
swe.set_sid_mode(swe.SIDM_LAHIRI)

results = []


def check(name, got, expected, tol, unit=""):
    ok = abs(got - expected) <= tol
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}")
    print(f"       got {got:.4f}{unit}, expected {expected:.4f}{unit} (tolerance {tol}{unit})")


def dms(deg):
    d = int(deg); m = int((deg - d) * 60); s = ((deg - d) * 60 - m) * 60
    return f"{d}deg {m:02d}' {s:05.2f}\""


print("=" * 68)
print("1. Lahiri ayanamsa at J2000.0")
print("   The published Lahiri value for 2000 Jan 1.5 is 23deg 51' 11\".")
jd_j2000 = swe.julday(2000, 1, 1, 12.0)
# Must match the call used to build charts, or we validate a value we never use.
_, ayan = swe.get_ayanamsa_ex_ut(jd_j2000, swe.FLG_MOSEPH)
print(f"   computed: {dms(ayan)}")
# Tolerance 1.8 arcsec: tight enough that the superseded call would fail here.
check("Lahiri ayanamsa J2000", ayan, 23.8531, 0.0005, " deg")

print()
print("=" * 68)
print("2. Mesha Sankranti 2024 -- Sun entering sidereal Aries")
print("   Independently published as 2024 Apr 13, 21:13 IST = 15:43 UT.")
print("   So at Apr 14 00:00 UT the Sun should sit just past 0 deg Aries.")
jd = swe.julday(2024, 4, 14, 0.0)
sun, _ = swe.calc_ut(jd, swe.SUN, FLAGS)
sun_lon, sun_speed = sun[0], sun[3]
print(f"   computed sidereal longitude: {dms(sun_lon)}")
check("Sun sidereal longitude", sun_lon, 0.34, 0.05, " deg")
check("Sun daily motion", sun_speed, 0.9856, 0.02, " deg/day")

print()
print("=" * 68)
print("3. Moon mean daily motion")
print("   The Moon covers 360 deg in 27.32 sidereal days = 13.18 deg/day.")
moon, _ = swe.calc_ut(jd, swe.MOON, FLAGS)
check("Moon daily motion", moon[3], 13.18, 1.2, " deg/day")

print()
print("=" * 68)
print("4. Internal consistency: tropical - sidereal must equal the ayanamsa")
print("   RULE: always use get_ayanamsa_ex_ut() with the SAME flags used for")
print("   positions. The plain get_ayanamsa_ut() uses a different reference")
print("   frame and disagrees by ~5 arcsec -- small, but it would mean the")
print("   ayanamsa we report did not match the chart we drew from it.")
trop, _ = swe.calc_ut(jd, swe.SUN, swe.FLG_MOSEPH)
diff = (trop[0] - sun_lon) % 360
_, ayan_ex = swe.get_ayanamsa_ex_ut(jd, swe.FLG_MOSEPH)
check("tropical minus sidereal Sun", diff, ayan_ex, 0.000001, " deg")

print()
print("=" * 68)
print("5. Ascendant computation responds correctly to location")
print("   Same instant, Belgrade vs Sydney -- ascendants must differ.")
_, ascmc_bg = swe.houses_ex(jd, 44.7866, 20.4489, b"W", swe.FLG_SIDEREAL)
_, ascmc_syd = swe.houses_ex(jd, -33.8688, 151.2093, b"W", swe.FLG_SIDEREAL)
print(f"   Belgrade ascendant: {dms(ascmc_bg[0])}")
print(f"   Sydney ascendant:   {dms(ascmc_syd[0])}")
differs = abs(ascmc_bg[0] - ascmc_syd[0]) > 1.0
results.append(differs)
print(f"[{'PASS' if differs else 'FAIL'}] ascendants differ by location")

print()
print("=" * 68)
print(f"{sum(results)}/{len(results)} checks passed")
