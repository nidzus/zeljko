"""Vimshottari dasha -- the 120-year cycle that answers "when".

Pure arithmetic off the Moon's exact position within its nakshatra. No
interpretation, no model involvement. The timing strip reads from here.

One choice is not universal and must stay explicit: the length of a "year".
Mainstream software uses the Gregorian mean year (365.2425 days); some schools
use a 360-day savana year. Over a 20-year mahadasha that is a 105-day
difference, so it is a parameter, never a hidden constant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import swisseph as swe

# The cycle, in nakshatra order. Ashwini belongs to Ketu, and it repeats every
# nine nakshatras. The years sum to 120.
VIMSHOTTARI = [
    ("Ketu", 7), ("Venus", 20), ("Sun", 6), ("Moon", 10), ("Mars", 7),
    ("Rahu", 18), ("Jupiter", 16), ("Saturn", 19), ("Mercury", 17),
]
TOTAL_YEARS = 120
NAK_ARC = 360.0 / 27

GREGORIAN_YEAR = 365.2425
SAVANA_YEAR = 360.0

LEVEL_NAMES = {1: "Mahadasha", 2: "Antardasha", 3: "Pratyantardasha"}


def jd_to_datetime(jd: float) -> datetime:
    y, m, d, hour = swe.revjul(jd)
    hh = int(hour)
    mm = int((hour - hh) * 60)
    ss = int(round(((hour - hh) * 60 - mm) * 60))
    if ss == 60:
        ss, mm = 0, mm + 1
    if mm == 60:
        mm, hh = 0, hh + 1
    if hh == 24:
        hh = 23; mm = 59; ss = 59
    return datetime(y, m, d, hh, mm, ss)


@dataclass
class Period:
    lord: str
    level: int                       # 1 mahadasha, 2 antardasha, 3 pratyantar
    start_jd: float
    end_jd: float
    children: list["Period"] = field(default_factory=list)

    @property
    def start(self) -> datetime:
        return jd_to_datetime(self.start_jd)

    @property
    def end(self) -> datetime:
        return jd_to_datetime(self.end_jd)

    @property
    def length_days(self) -> float:
        return self.end_jd - self.start_jd

    def contains(self, jd: float) -> bool:
        return self.start_jd <= jd < self.end_jd

    def label(self) -> str:
        return self.lord

    def __str__(self) -> str:
        return (f"{LEVEL_NAMES[self.level]:<16} {self.lord:<8} "
                f"{self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}")


def _cycle_from(lord_index: int):
    """Sub-periods run in the same order, beginning with the parent's own lord."""
    for i in range(9):
        yield VIMSHOTTARI[(lord_index + i) % 9]


def _subdivide(parent: Period, parent_lord_index: int, target_level: int) -> None:
    span = parent.end_jd - parent.start_jd
    cursor = parent.start_jd
    for offset in range(9):
        idx = (parent_lord_index + offset) % 9
        lord, years = VIMSHOTTARI[idx]
        # A sub-period takes the same share of its parent as its lord's years
        # take of the 120-year whole.
        length = span * years / TOTAL_YEARS
        child = Period(lord=lord, level=parent.level + 1,
                       start_jd=cursor, end_jd=cursor + length)
        parent.children.append(child)
        if child.level < target_level:
            _subdivide(child, idx, target_level)
        cursor += length
    # Absorb floating-point drift into the final child so the sub-periods
    # exactly fill the parent -- no gap, no overlap.
    parent.children[-1].end_jd = parent.end_jd


@dataclass
class DashaTree:
    birth_jd: float
    moon_longitude: float
    year_days: float
    balance_years: float          # of the birth mahadasha, remaining at birth
    periods: list[Period]

    def at(self, jd: float) -> list[Period]:
        """The nested periods running at a given instant, outermost first."""
        chain, pool = [], self.periods
        while pool:
            for p in pool:
                if p.contains(jd):
                    chain.append(p)
                    pool = p.children
                    break
            else:
                break
        return chain

    def describe(self, jd: float) -> str:
        chain = self.at(jd)
        return " / ".join(p.lord for p in chain) if chain else "outside computed range"


def compute(
    moon_longitude: float,
    birth_jd: float,
    levels: int = 3,
    year_days: float = GREGORIAN_YEAR,
    cycles: int = 1,
) -> DashaTree:
    """Build the dasha tree for a nativity.

    The mahadasha running at birth began BEFORE birth -- the Moon had already
    travelled part way through its nakshatra. We reconstruct that start so the
    sequence is continuous rather than starting mid-period.
    """
    nak = int(moon_longitude // NAK_ARC)
    elapsed = (moon_longitude % NAK_ARC) / NAK_ARC
    lord_index = nak % 9
    _, years = VIMSHOTTARI[lord_index]

    balance_years = (1 - elapsed) * years
    first_start_jd = birth_jd - elapsed * years * year_days

    periods: list[Period] = []
    cursor = first_start_jd
    for step in range(9 * cycles):
        idx = (lord_index + step) % 9
        lord, yrs = VIMSHOTTARI[idx]
        p = Period(lord=lord, level=1, start_jd=cursor, end_jd=cursor + yrs * year_days)
        if levels > 1:
            _subdivide(p, idx, levels)
        periods.append(p)
        cursor = p.end_jd

    return DashaTree(
        birth_jd=birth_jd,
        moon_longitude=moon_longitude,
        year_days=year_days,
        balance_years=balance_years,
        periods=periods,
    )
