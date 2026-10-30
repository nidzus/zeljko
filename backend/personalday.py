"""Whether a day is good FOR THIS PERSON, rather than good in general.

The panchanga is the same for everyone standing in the same place. Tara bala
and Chandra bala are not: both are counted from the natal Moon, so two people
can meet the same tithi and the same nakshatra on opposite terms.

Tara bala counts the nakshatras from the one you were born under to the one the
Moon is passing now, in nines. Chandra bala is the Moon's sign relative to your
natal Moon's sign. Between them they are the classical answer to "is today a
good day for me", which the panchanga alone cannot give.

Neither is a verdict on its own. They qualify an answer reached some other way
-- a favourable Tara does not make a bad decision good.
"""
from __future__ import annotations

from dataclasses import dataclass

import swisseph as swe

from . import dasha, ephemeris, transits

MINUTE = 1.0 / 1440.0
NAK_ARC = 360.0 / 27

TARAS = [
    ("Janma", "your own star", False),
    ("Sampat", "gain", True),
    ("Vipat", "loss", False),
    ("Kshema", "well-being", True),
    ("Pratyari", "obstruction", False),
    ("Sadhaka", "accomplishment", True),
    ("Vadha", "harm", False),
    ("Mitra", "friend", True),
    ("Ati Mitra", "close friend", True),
]

# The Moon's sign counted from the natal Moon's sign. This is the common set;
# schools differ at the margins, which is noted in the output rather than
# resolved silently.
CHANDRA_GOOD = (1, 3, 6, 7, 10, 11)
CHANDRA_POOR = (4, 8, 12)


def _moon(jd: float, ayanamsa: str = "LAHIRI") -> float:
    return transits.state(jd, "Moon", ayanamsa)[0]


def _tara_index(jd: float, natal_nakshatra: int, ayanamsa: str) -> int:
    return (int(_moon(jd, ayanamsa) // NAK_ARC) - natal_nakshatra) % 9


def _changes_at(jd: float, natal_nakshatra: int, ayanamsa: str) -> float:
    """When the Moon moves on and the Tara changes with it."""
    start = _tara_index(jd, natal_nakshatra, ayanamsa)
    lo, hi = jd, jd + 0.05
    for _ in range(80):
        if _tara_index(hi, natal_nakshatra, ayanamsa) != start:
            break
        lo, hi = hi, hi + 0.05
    else:
        return hi
    while hi - lo > MINUTE:
        mid = (lo + hi) / 2
        if _tara_index(mid, natal_nakshatra, ayanamsa) != start:
            hi = mid
        else:
            lo = mid
    return hi


@dataclass
class PersonalDay:
    tara: str
    tara_meaning: str
    tara_number: int
    tara_favourable: bool
    tara_changes_at: str
    cycle: int                  # 1, 2 or 3 -- which pass through the nine
    chandra_house: int
    chandra_favourable: bool
    moon_nakshatra: str
    verdict: str
    note: str

    def as_dict(self) -> dict:
        return {
            "tara": {"name": self.tara, "means": self.tara_meaning,
                     "number": self.tara_number, "cycle": self.cycle,
                     "favourable": self.tara_favourable,
                     "changes_at": self.tara_changes_at},
            "chandra_bala": {"house_from_natal_moon": self.chandra_house,
                             "favourable": self.chandra_favourable},
            "moon_nakshatra": self.moon_nakshatra,
            "verdict": self.verdict,
            "note": self.note,
        }


def at(chart: ephemeris.Chart, jd: float) -> PersonalDay:
    """Tara bala and Chandra bala for this chart, at this moment."""
    ayanamsa = chart.ayanamsa_name
    natal_moon = chart.get("Moon")
    moon_lon = _moon(jd, ayanamsa)
    moon_nak = int(moon_lon // NAK_ARC)

    steps = (moon_nak - natal_moon.nakshatra_index) % 27
    index = steps % 9
    name, meaning, good_tara = TARAS[index]
    cycle = steps // 9 + 1

    house = ((int(moon_lon // 30) - natal_moon.sign_index) % 12) + 1
    good_chandra = house in CHANDRA_GOOD

    if good_tara and good_chandra:
        verdict = "favourable"
    elif not good_tara and not good_chandra:
        verdict = "poor"
    else:
        verdict = "mixed"

    notes = []
    if index == 0:
        notes.append("Janma tara is your own birth star. Opinion divides: "
                     "avoided for new undertakings, but held suitable for "
                     "things concerning yourself.")
    if house in CHANDRA_POOR:
        notes.append(f"The Moon is in the {house}th from your natal Moon, "
                     f"which is among the weaker placements.")
    if cycle > 1:
        notes.append(f"This is the {cycle}{'nd' if cycle == 2 else 'rd'} of the "
                     f"three cycles; several schools read the first as the "
                     f"strongest and later ones as milder.")
    notes.append("Qualifies an answer, does not make one. A good Tara will not "
                 "rescue a decision that is wrong on its merits.")

    return PersonalDay(
        tara=name, tara_meaning=meaning, tara_number=index + 1,
        tara_favourable=good_tara,
        tara_changes_at=dasha.jd_to_datetime(
            _changes_at(jd, natal_moon.nakshatra_index, ayanamsa)
        ).strftime("%Y-%m-%d %H:%M UT"),
        cycle=cycle,
        chandra_house=house, chandra_favourable=good_chandra,
        moon_nakshatra=ephemeris.NAKSHATRAS[moon_nak],
        verdict=verdict, note=" ".join(notes))


def window(chart: ephemeris.Chart, start_jd: float, days: int = 14,
           hour: float = 9.0) -> list[dict]:
    """Day-by-day, so a good stretch can be found rather than described.

    Sampled at one hour each day: the Tara changes when the Moon changes
    nakshatra, which is roughly daily but not at midnight, so a day can carry
    two. `tara_changes_at` says when.
    """
    out = []
    for offset in range(days):
        jd = start_jd + offset + hour / 24.0
        day = at(chart, jd)
        out.append({"date": dasha.jd_to_datetime(jd).strftime("%Y-%m-%d"),
                    **day.as_dict()})
    return out


def best_days(chart: ephemeris.Chart, start_jd: float,
              days: int = 30) -> list[dict]:
    """Only the days where both measures agree this chart is favoured."""
    return [d for d in window(chart, start_jd, days) if d["verdict"] == "favourable"]
