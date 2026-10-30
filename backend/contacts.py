"""Dated moments when a transiting graha reaches a natal point.

"Saturn is in your 10th" stays true for two and a half years, which is no use
for timing. "Saturn's aspect falls exactly on your natal Moon on 14 June" is a
date you can plan around. That is the difference this makes.

Conjunctions alone are too sparse to be worth much -- a slow graha meets a
given natal point once every twelve or thirty years -- so aspects are counted
too. Graha drishti is classically a whole-sign relation; taking it to the exact
degree is a refinement, and the one that yields a date rather than a season.
Every contact says which aspect it is.

Retrogression means a graha can reach the same point three times: going
forward, back, and forward again. Those passes are reported separately, since
they are three occasions and not one.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import dasha, ephemeris, transits, yogas

MINUTE = 1.0 / 1440.0

# Slow enough that a contact means something. The Moon would give a contact
# every few days and drown everything else.
DEFAULT_TRANSITING = ("Jupiter", "Saturn", "Mars", "Rahu", "Ketu")

SCAN_STEP = {"Mars": 1.0, "Jupiter": 2.0, "Saturn": 2.0,
             "Rahu": 2.0, "Ketu": 2.0, "Sun": 0.5, "Venus": 0.5,
             "Mercury": 0.5, "Moon": 0.1}


def _aspect_angles(body: str) -> dict[float, str]:
    """The separations at which this graha touches a point, and their names."""
    angles = {0.0: "conjunction"}
    for offset in yogas.aspect_offsets(body):
        ordinal = {3: "3rd", 4: "4th", 5: "5th", 7: "7th", 8: "8th",
                   9: "9th", 10: "10th"}[offset]
        angles[(offset - 1) * 30.0] = f"{ordinal} aspect"
    return angles


@dataclass
class Contact:
    jd: float
    transiting: str
    natal: str
    aspect: str
    retrograde: bool
    natal_house: int

    def as_dict(self) -> dict:
        return {
            "date": dasha.jd_to_datetime(self.jd).strftime("%Y-%m-%d"),
            "transiting": self.transiting,
            "aspect": self.aspect,
            "natal_point": self.natal,
            "natal_house": self.natal_house,
            "transiting_retrograde": self.retrograde,
        }


def _separation(jd: float, body: str, target: float, angle: float,
                ayanamsa: str) -> float:
    """How far this graha is from making the contact, signed, -180 to 180."""
    lon = transits.state(jd, body, ayanamsa)[0]
    return (lon - target - angle + 180) % 360 - 180


def find(chart: ephemeris.Chart, start_jd: float, end_jd: float,
         transiting: tuple[str, ...] = DEFAULT_TRANSITING,
         natal_points: tuple[str, ...] | None = None) -> list[Contact]:
    """Every exact contact in the window, in date order."""
    ayanamsa = chart.ayanamsa_name
    targets: list[tuple[str, float, int]] = [
        ("Lagna", chart.ascendant.longitude, 1)]
    for p in chart.positions:
        targets.append((p.name, p.longitude, p.house))
    if natal_points:
        targets = [t for t in targets if t[0] in natal_points]

    out: list[Contact] = []
    for body in transiting:
        step = SCAN_STEP.get(body, 2.0)
        for angle, label in _aspect_angles(body).items():
            for name, target, house in targets:
                jd = start_jd
                previous = _separation(jd, body, target, angle, ayanamsa)
                while jd < end_jd:
                    jd += step
                    current = _separation(jd, body, target, angle, ayanamsa)
                    # Ignore the jump where the measure wraps at 180 degrees;
                    # a genuine crossing moves only a little between samples.
                    if (previous < 0) != (current < 0) and abs(current - previous) < 90:
                        lo, hi = jd - step, jd
                        for _ in range(40):
                            mid = (lo + hi) / 2
                            if (_separation(mid, body, target, angle,
                                            ayanamsa) < 0) == (previous < 0):
                                lo = mid
                            else:
                                hi = mid
                        speed = transits.state(hi, body, ayanamsa)[1]
                        out.append(Contact(jd=hi, transiting=body, natal=name,
                                           aspect=label, retrograde=speed < 0,
                                           natal_house=house))
                    previous = current
    out.sort(key=lambda c: c.jd)
    return out


def summary(chart: ephemeris.Chart, start_jd: float, end_jd: float,
            **kwargs) -> dict:
    found = find(chart, start_jd, end_jd, **kwargs)
    passes: dict[tuple, int] = {}
    for c in found:
        key = (c.transiting, c.natal, c.aspect)
        passes[key] = passes.get(key, 0) + 1
    repeated = [f"{t} {a} to natal {n} ({count} passes)"
                for (t, n, a), count in passes.items() if count > 1]
    return {
        "from": dasha.jd_to_datetime(start_jd).strftime("%Y-%m-%d"),
        "to": dasha.jd_to_datetime(end_jd).strftime("%Y-%m-%d"),
        "count": len(found),
        "contacts": [c.as_dict() for c in found],
        "repeated_passes": repeated,
        "note": "Graha drishti is classically a whole-sign relation; these are "
                "taken to the exact degree, which is what turns an aspect into "
                "a date. Where a contact repeats, the graha crossed the point "
                "going forward, turned back over it, and crossed again -- three "
                "occasions, not one.",
    }
