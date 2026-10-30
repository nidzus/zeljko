"""Numeric strength, so grahas can be compared rather than just described.

`strength.py` says whether a graha is exalted, combust, angular. This puts
numbers on it, which is what you need when two factors point opposite ways and
one of them has to win.

WHAT THIS IS NOT. Shadbala proper has six sources with many sub-components,
several of which vary between schools and none of which have a published
invariant to check an implementation against. Five well-defined components are
computed here:

    uchcha       distance from the point of deepest debilitation
    dig          distance from the direction the graha is strongest in
    naisargika   the fixed natural order of strength
    paksha       the Moon's phase, which favours benefics or malefics
    nathonnatha  strength by day or by night

Omitted: saptavargaja, kendradi, ojhayugma, drekkana, cheshta, the calendar
components of kala bala, and drik bala.

So the totals here are NOT comparable to the classical minimum strengths a
graha is supposed to reach -- those assume all six sources. They are for
comparing grahas within one chart, which is the question that actually comes
up. Every result says so.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ephemeris, strength

VIRUPAS_PER_RUPA = 60.0

# Naisargika bala is a fixed order: the Sun strongest, Saturn weakest, in even
# steps of a seventh. Deriving it rather than tabulating it keeps it checkable.
NAISARGIKA_RANK = {"Sun": 7, "Moon": 6, "Venus": 5, "Jupiter": 4,
                   "Mercury": 3, "Mars": 2, "Saturn": 1}

# Which of the four angles each graha draws directional strength from.
DIG_DIRECTION = {"Jupiter": "ascendant", "Mercury": "ascendant",
                 "Sun": "midheaven", "Mars": "midheaven",
                 "Saturn": "descendant",
                 "Moon": "nadir", "Venus": "nadir"}

NATURAL_BENEFICS = ("Jupiter", "Venus")
NATURAL_MALEFICS = ("Sun", "Mars", "Saturn")

# Strong at midnight, strong at noon, or neither.
NIGHT_STRONG = ("Moon", "Mars", "Saturn")
DAY_STRONG = ("Sun", "Jupiter", "Venus")


def _arc(a: float, b: float) -> float:
    """Shortest angular separation, 0 to 180."""
    return abs((a - b + 180) % 360 - 180)


def _proportional(distance_from_weakest: float) -> float:
    """Sixty virupas at the strong point, none at the opposite one."""
    return 60.0 * distance_from_weakest / 180.0


def uchcha_bala(body: str, longitude: float) -> float:
    """Strength from how near exaltation the graha stands."""
    if body not in strength.EXALTATION:
        return 0.0
    sign, degree = strength.EXALTATION[body]
    exaltation_point = sign * 30 + degree
    debilitation_point = (exaltation_point + 180) % 360
    return _proportional(_arc(longitude, debilitation_point))


def dig_bala(body: str, longitude: float, chart: ephemeris.Chart) -> float:
    """Strength from standing in the direction this graha belongs to."""
    direction = DIG_DIRECTION.get(body)
    if direction is None:
        return 0.0
    angles = {
        "ascendant": chart.ascendant.longitude,
        "descendant": (chart.ascendant.longitude + 180) % 360,
        "midheaven": chart.midheaven,
        "nadir": (chart.midheaven + 180) % 360,
    }
    strongest = angles[direction]
    weakest = (strongest + 180) % 360
    return _proportional(_arc(longitude, weakest))


def naisargika_bala(body: str) -> float:
    rank = NAISARGIKA_RANK.get(body)
    return 0.0 if rank is None else 60.0 * rank / 7.0


def paksha_bala(body: str, chart: ephemeris.Chart) -> float:
    """The Moon's phase favours benefics as it waxes, malefics as it wanes."""
    elongation = _arc(chart.get("Moon").longitude, chart.get("Sun").longitude)
    waxing_share = 60.0 * elongation / 180.0
    if body in NATURAL_BENEFICS:
        return waxing_share
    if body in NATURAL_MALEFICS:
        return 60.0 - waxing_share
    if body == "Moon":
        return waxing_share
    return 30.0        # Mercury takes the character of its company


def nathonnatha_bala(body: str, birth_hour_from_midnight: float) -> float:
    """Some grahas are strong by night, some by day, Mercury always."""
    if body == "Mercury":
        return 60.0
    # Distance from midnight, as a fraction of the half-day.
    from_midnight = abs((birth_hour_from_midnight % 24) - 12) / 12.0
    night_strength = 60.0 * from_midnight
    if body in NIGHT_STRONG:
        return night_strength
    if body in DAY_STRONG:
        return 60.0 - night_strength
    return 0.0


@dataclass
class Shadbala:
    body: str
    uchcha: float
    dig: float
    naisargika: float
    paksha: float
    nathonnatha: float

    @property
    def total_virupas(self) -> float:
        return (self.uchcha + self.dig + self.naisargika
                + self.paksha + self.nathonnatha)

    @property
    def rupas(self) -> float:
        return self.total_virupas / VIRUPAS_PER_RUPA

    def as_dict(self) -> dict:
        return {
            "body": self.body,
            "components_virupas": {
                "uchcha": round(self.uchcha, 1),
                "dig": round(self.dig, 1),
                "naisargika": round(self.naisargika, 1),
                "paksha": round(self.paksha, 1),
                "nathonnatha": round(self.nathonnatha, 1),
            },
            "total_virupas": round(self.total_virupas, 1),
            "rupas": round(self.rupas, 2),
        }


def assess(chart: ephemeris.Chart, birth_hour: float = 12.0) -> dict:
    """Rank the seven grahas by the strength components computed here."""
    out = []
    for body in NAISARGIKA_RANK:
        p = chart.get(body)
        out.append(Shadbala(
            body=body,
            uchcha=uchcha_bala(body, p.longitude),
            dig=dig_bala(body, p.longitude, chart),
            naisargika=naisargika_bala(body),
            paksha=paksha_bala(body, chart),
            nathonnatha=nathonnatha_bala(body, birth_hour),
        ))
    out.sort(key=lambda s: s.total_virupas, reverse=True)
    return {
        "ranked": [s.as_dict() for s in out],
        "strongest": out[0].body,
        "weakest": out[-1].body,
        "components_included": ["uchcha", "dig", "naisargika", "paksha",
                                "nathonnatha"],
        "components_omitted": ["saptavargaja", "kendradi", "ojhayugma",
                               "drekkana", "cheshta", "kala calendar terms",
                               "drik"],
        "caveat": "A partial Shadbala. Use it to compare grahas WITHIN this "
                  "chart -- which is the question that comes up when two "
                  "factors disagree. Do not compare the totals against the "
                  "classical minimum strengths, which assume all six sources.",
    }
