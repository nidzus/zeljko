"""Finding the moments when a situation actually changes.

Planetary motion is continuous, but a nativity's situation is not: it changes
at discrete events -- a graha entering a new sign (and therefore a new house),
turning retrograde or direct, or a dasha period handing over. Those events are
the only places the timing strip can change colour, so they are what we
compute. Smooth motion is decoration.

Everything here is root-finding on functions the ephemeris provides. No
interpretation, no model.
"""
from __future__ import annotations

from dataclasses import dataclass

import swisseph as swe

from . import dasha, ephemeris

MINUTE = 1.0 / 1440.0     # in days, the precision we refine events to

# How coarsely each body can be scanned before an event could be missed.
# The Moon crosses a sign in 2.25 days; Saturn takes 2.5 years.
SCAN_STEP_DAYS = {
    "Moon": 0.2, "Sun": 1.0, "Mercury": 1.0, "Venus": 1.0,
    "Mars": 2.0, "Jupiter": 4.0, "Saturn": 6.0, "Rahu": 4.0, "Ketu": 4.0,
}

_BODY = {name: code for name, _, code in ephemeris.GRAHAS}


def state(jd: float, body: str, ayanamsa: str = "LAHIRI") -> tuple[float, float]:
    """Sidereal longitude and speed of one graha. Ketu is derived from Rahu."""
    swe.set_sid_mode(ephemeris.AYANAMSAS[ayanamsa])
    flags = swe.FLG_MOSEPH | swe.FLG_SPEED | swe.FLG_SIDEREAL
    if body == "Ketu":
        v, _ = swe.calc_ut(jd, _BODY["Rahu"], flags)
        return (v[0] + 180.0) % 360.0, v[3]
    v, _ = swe.calc_ut(jd, _BODY[body], flags)
    return v[0] % 360.0, v[3]


@dataclass
class Event:
    kind: str          # "ingress", "station", "dasha"
    jd: float
    body: str
    detail: str
    sign_index: int = -1
    house: int = 0

    @property
    def when(self):
        return dasha.jd_to_datetime(self.jd)

    def __str__(self) -> str:
        h = f" (house {self.house})" if self.house else ""
        return f"{self.when:%Y-%m-%d %H:%M}  {self.body:<8} {self.detail}{h}"


def _bisect(lo: float, hi: float, changed) -> float:
    """Narrow an interval known to contain a change down to one minute."""
    while hi - lo > MINUTE:
        mid = (lo + hi) / 2
        if changed(lo, mid):
            hi = mid
        else:
            lo = mid
    return hi


def find_ingresses(start_jd, end_jd, body, ayanamsa="LAHIRI") -> list[Event]:
    """When this graha crosses from one sign into the next."""
    step = SCAN_STEP_DAYS[body]
    sign_at = lambda jd: int(state(jd, body, ayanamsa)[0] // 30)
    out, jd, prev = [], start_jd, None
    while jd <= end_jd:
        s = sign_at(jd)
        if prev is not None and s != prev:
            exact = _bisect(jd - step, jd, lambda a, b: sign_at(a) != sign_at(b))
            new_sign = sign_at(exact + MINUTE)
            out.append(Event(
                kind="ingress", jd=exact, body=body,
                detail=f"enters {ephemeris.SIGNS[new_sign][1]}",
                sign_index=new_sign,
            ))
        prev = s
        jd += step
    return out


def find_stations(start_jd, end_jd, body, ayanamsa="LAHIRI") -> list[Event]:
    """When this graha turns retrograde or direct.

    The lunar nodes move retrograde permanently, so they never station.
    """
    if body in ("Rahu", "Ketu", "Sun", "Moon"):
        return []
    step = SCAN_STEP_DAYS[body]
    direction = lambda jd: state(jd, body, ayanamsa)[1] < 0
    out, jd, prev = [], start_jd, None
    while jd <= end_jd:
        d = direction(jd)
        if prev is not None and d != prev:
            exact = _bisect(jd - step, jd, lambda a, b: direction(a) != direction(b))
            out.append(Event(
                kind="station", jd=exact, body=body,
                detail="turns retrograde" if d else "turns direct",
            ))
        prev = d
        jd += step
    return out


def find_dasha_changes(tree: dasha.DashaTree, start_jd, end_jd,
                       max_level: int = 2) -> list[Event]:
    """When a dasha period hands over, to the requested depth."""
    out = []

    def walk(periods):
        for p in periods:
            if start_jd <= p.start_jd <= end_jd:
                out.append(Event(
                    kind="dasha", jd=p.start_jd, body=p.lord,
                    detail=f"{dasha.LEVEL_NAMES[p.level].lower()} begins",
                ))
            if p.level < max_level and p.end_jd >= start_jd and p.start_jd <= end_jd:
                walk(p.children)

    walk(tree.periods)
    return out


def timeline(
    chart: ephemeris.Chart,
    tree: dasha.DashaTree | None,
    start_jd: float,
    end_jd: float,
    bodies: list[str] | None = None,
    dasha_levels: int = 2,
) -> list[Event]:
    """Every moment in the window where this nativity's situation changes."""
    bodies = bodies or [name for name, _, _ in ephemeris.GRAHAS] + ["Ketu"]
    events: list[Event] = []
    for b in bodies:
        events += find_ingresses(start_jd, end_jd, b, chart.ayanamsa_name)
        events += find_stations(start_jd, end_jd, b, chart.ayanamsa_name)
    if tree is not None:
        events += find_dasha_changes(tree, start_jd, end_jd, dasha_levels)

    # An ingress means nothing until it is placed against the nativity: the
    # sign it enters is a house of THIS chart.
    for e in events:
        if e.sign_index >= 0:
            e.house = chart.house_of(e.sign_index)

    events.sort(key=lambda e: e.jd)
    return events
