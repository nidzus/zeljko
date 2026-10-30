"""Checks on chart drawing."""
import sys
sys.path.insert(0, ".")

import xml.etree.ElementTree as ET

from backend import chartsvg, ephemeris, timeplace

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
natal = chartsvg.north_indian(chart, caption="Natal")
overlay = chartsvg.north_indian(chart, transit_date="2026-08-28",
                                highlight=[1, 10], caption="With transits")

print("=" * 72)
print("1. Both renders are well-formed SVG")
for label, svg in [("natal", natal), ("with transits", overlay)]:
    try:
        ET.fromstring(svg)
        ok, why = True, f"{len(svg)} bytes"
    except ET.ParseError as e:
        ok, why = False, str(e)
    check(f"{label} parses as XML", ok, why)

print()
print("=" * 72)
print("2. Every graha appears, and the lagna is marked")
for p in chart.positions:
    check(f"{p.name} is drawn", chartsvg.SHORT[p.name] in natal)
check("the ascendant is marked", ">As" in natal or "As " in natal)

print()
print("=" * 72)
print("3. All twelve houses carry their sign number")
numbers = [chart.sign_in_house(h) + 1 for h in range(1, 13)]
missing = [n for n in numbers if f">{n}</text>" not in natal]
check("no house is left unlabelled", not missing,
      f"signs drawn: {sorted(set(numbers))}")

print()
print("=" * 72)
print("4. The transit overlay adds without replacing")
check("the overlay is larger than the natal alone", len(overlay) > len(natal),
      f"{len(natal)} -> {len(overlay)} bytes")
check("natal placements survive the overlay",
      all(chartsvg.SHORT[p.name] in overlay for p in chart.positions))
check("transiting grahas are styled apart", 'class="t"' in overlay
      and 'class="t"' not in natal,
      "natal and transiting are separate classes, so they read differently")
check("the legend explains the two", "transiting in blue" in overlay
      and "transiting in blue" not in natal)

print()
print("=" * 72)
print("5. Highlighting marks the houses a question turns on")
check("highlights are drawn", overlay.count('class="h"') == 2,
      "two houses tinted")
check("and are absent when not asked for", 'class="h"' not in natal)

print()
print("=" * 72)
print("6. It works standalone, in both light and dark")
check("styling travels with the file", "<style>" in natal)
check("a dark variant is included",
      "prefers-color-scheme:dark" in natal,
      "no host stylesheet needed, and it will not vanish on a dark background")
check("nothing is loaded from the network",
      "http://" not in natal.replace('xmlns="http://www.w3.org/2000/svg"', ""),
      "self-contained")

print()
print("=" * 72)
print("7. A crowded house stays inside its cell")
crowded = chartsvg._cell_lines(["Su", "Mo", "Ma", "Me", "Ju", "Ve"])
check("six grahas wrap to three rows of two", crowded == ["Su Mo", "Ma Me", "Ju Ve"],
      str(crowded))

print()
print("=" * 72)
print("8. A bad request is refused rather than drawn wrong")
try:
    chartsvg.north_indian(chart, transit_date="not-a-date")
    check("an unparseable date is rejected", False, "it drew something")
except ValueError:
    check("an unparseable date is rejected", True)

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
