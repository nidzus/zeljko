"""Checks on the coordinate parser, against the formats Google Maps emits."""
import sys
sys.path.insert(0, ".")

from backend.coords import CoordinateError, parse

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


def close(text, lat, lon, tol=1e-4):
    try:
        c = parse(text)
    except CoordinateError as e:
        return False, f"raised: {e}"
    ok = abs(c.latitude - lat) < tol and abs(c.longitude - lon) < tol
    return ok, f"{text!r} -> {c}"


print("=" * 72)
print("1. The formats Google Maps actually produces")
cases = [
    ("44.7866, 20.4489", *BG),                        # copy coordinates
    ("44.7866,20.4489", *BG),                         # no space
    ("44.7866 20.4489", *BG),                         # space separated
    ('44°47\'11.76"N 20°26\'56.04"E', *BG), # place card, DMS
    ("44 47 11.76 N, 20 26 56.04 E", *BG),            # DMS, punctuation stripped
    ("N44.7866 E20.4489", *BG),                       # hemisphere leading
    ("44°47.11'N 20°26.934'E", 44.78517, 20.4489),  # degrees and minutes
]
for text, lat, lon in cases:
    ok, detail = close(text, lat, lon)
    check(f"parses {text[:34]}", ok, detail)

print()
print("=" * 72)
print("2. Southern and western hemispheres")
for text, lat, lon in [
    ("-33.8688, 151.2093", -33.8688, 151.2093),       # Sydney, signed
    ('33°52\'7.7"S 151°12\'33.5"E', -33.8688, 151.2093),
    ("40.7128, -74.0060", 40.7128, -74.0060),         # New York, signed
    ('40°42\'46"N 74°0\'21.6"W', 40.7128, -74.0060),
]:
    ok, detail = close(text, lat, lon)
    check(f"parses {text[:34]}", ok, detail)

print()
print("=" * 72)
print("3. Axes are taken from the hemisphere letters, not from the order")
ok, detail = close("20.4489E, 44.7866N", *BG)
check("longitude first is still read correctly", ok, detail)

print()
print("=" * 72)
print("4. Nonsense is refused rather than guessed at")
for label, text in [
    ("empty input", ""),
    ("no numbers", "somewhere near the sea"),
    ("only one number", "44.7866"),
    ("latitude out of range", "144.7866, 20.4489"),
    ("longitude out of range", "44.7866, 220.4489"),
    ("three coordinates", "1N 2E 3N"),
]:
    try:
        got = parse(text)
        check(label, False, f"accepted {text!r} as {got}")
    except CoordinateError:
        check(label, True)

print()
print("=" * 72)
print("5. Precision is preserved rather than rounded away")
c = parse("44.786568, 20.448921")
check("full decimal precision kept",
      abs(c.latitude - 44.786568) < 1e-9 and abs(c.longitude - 20.448921) < 1e-9,
      str(c))

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
