"""The five limbs of the day, for questions at day scale.

Month-and-year questions run on dashas and slow transits. "Should I have the
conversation today", "when this week should I sign" run on this instead: the
tithi, the weekday, the Moon's nakshatra, the yoga and the karana.

Each limb is reported with the time it ends, because that is the part that
matters. Knowing today is Trayodashi is trivia; knowing it gives way at 14:40
is what lets you place something inside it.

Traditional panchanga is reckoned from sunrise rather than midnight, so the
day's limbs are those in force at sunrise -- which is why a panchanga can
disagree with a naive midnight calculation about what day it is.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import swisseph as swe

from . import dasha, ephemeris

MINUTE = 1.0 / 1440.0

TITHI_NAMES = [
    "Pratipada", "Dvitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi",
    "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dvadashi",
    "Trayodashi", "Chaturdashi",
]

YOGA_NAMES = [
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda",
    "Sukarman", "Dhriti", "Shula", "Ganda", "Vriddhi", "Dhruva", "Vyaghata",
    "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyan", "Parigha", "Shiva",
    "Siddha", "Sadhya", "Shubha", "Shukla", "Brahma", "Indra", "Vaidhriti",
]

# Seven repeating karanas, then three fixed ones closing the lunar month, and
# one fixed one opening it.
MOVABLE_KARANAS = ["Bava", "Balava", "Kaulava", "Taitila", "Gara", "Vanija",
                   "Vishti"]
FIXED_KARANAS = ["Shakuni", "Chatushpada", "Naga"]
FIRST_KARANA = "Kimstughna"

VARA_NAMES = [
    ("Ravivara", "Sunday", "Sun"), ("Somavara", "Monday", "Moon"),
    ("Mangalavara", "Tuesday", "Mars"), ("Budhavara", "Wednesday", "Mercury"),
    ("Guruvara", "Thursday", "Jupiter"), ("Shukravara", "Friday", "Venus"),
    ("Shanivara", "Saturday", "Saturn"),
]

# Daylight is divided into eight parts; Rahu Kaal is one of them, and which one
# depends on the weekday. Indexed from Sunday, one-based part number.
RAHU_KAAL_PART = [8, 2, 7, 5, 6, 4, 3]


def _lon(jd: float, body: int, ayanamsa: str) -> float:
    swe.set_sid_mode(ephemeris.AYANAMSAS[ayanamsa])
    v, _ = swe.calc_ut(jd, body, swe.FLG_MOSEPH | swe.FLG_SIDEREAL)
    return v[0] % 360.0


def _elongation(jd: float, ayanamsa: str) -> float:
    """How far the Moon has pulled ahead of the Sun. Drives tithi and karana."""
    return (_lon(jd, swe.MOON, ayanamsa) - _lon(jd, swe.SUN, ayanamsa)) % 360.0


def _yoga_arc(jd: float, ayanamsa: str) -> float:
    return (_lon(jd, swe.SUN, ayanamsa) + _lon(jd, swe.MOON, ayanamsa)) % 360.0


def _ends_at(jd: float, index_of, ayanamsa: str, step: float = 0.02) -> float:
    """When the current division gives way to the next.

    Every limb is a fixed arc crossed by a monotonically advancing angle, so
    walk forward until the index changes, then narrow to the minute.
    """
    start = index_of(jd, ayanamsa)
    lo, hi = jd, jd + step
    for _ in range(200):
        if index_of(hi, ayanamsa) != start:
            break
        lo, hi = hi, hi + step
    else:
        return hi
    while hi - lo > MINUTE:
        mid = (lo + hi) / 2
        if index_of(mid, ayanamsa) != start:
            hi = mid
        else:
            lo = mid
    return hi


def _tithi_index(jd, ayanamsa):
    return int(_elongation(jd, ayanamsa) // 12)


def _karana_index(jd, ayanamsa):
    return int(_elongation(jd, ayanamsa) // 6)


def _nakshatra_index(jd, ayanamsa):
    return int(_lon(jd, swe.MOON, ayanamsa) // (360 / 27))


def _yoga_index(jd, ayanamsa):
    return int(_yoga_arc(jd, ayanamsa) // (360 / 27))


def karana_name(index: int) -> str:
    """Sixty karanas fill a lunar month: one fixed, fifty-six repeating, three fixed."""
    if index == 0:
        return FIRST_KARANA
    if index >= 57:
        return FIXED_KARANAS[index - 57]
    return MOVABLE_KARANAS[(index - 1) % 7]


def sun_times(jd: float, latitude: float, longitude: float) -> tuple[float, float]:
    """Sunrise and sunset bracketing the day that contains this instant."""
    geo = (longitude, latitude, 0.0)
    flags = swe.FLG_MOSEPH
    # Step back a day so a pre-dawn instant still finds its own sunrise.
    res, rise = swe.rise_trans(jd - 1, swe.SUN,
                               swe.CALC_RISE | swe.BIT_DISC_CENTER,
                               geo, 0.0, 0.0, flags)
    while rise[0] < jd - 1.0:
        res, rise = swe.rise_trans(rise[0] + 0.1, swe.SUN,
                                   swe.CALC_RISE | swe.BIT_DISC_CENTER,
                                   geo, 0.0, 0.0, flags)
    # The sunrise that opens the current panchanga day is the last one before now.
    latest = rise[0]
    while True:
        res, nxt = swe.rise_trans(latest + 0.1, swe.SUN,
                                  swe.CALC_RISE | swe.BIT_DISC_CENTER,
                                  geo, 0.0, 0.0, flags)
        if nxt[0] > jd:
            break
        latest = nxt[0]
    res, sset = swe.rise_trans(latest, swe.SUN,
                               swe.CALC_SET | swe.BIT_DISC_CENTER,
                               geo, 0.0, 0.0, flags)
    return latest, sset[0]


@dataclass
class Limb:
    name: str
    index: int
    ends: datetime

    def as_dict(self) -> dict:
        return {"name": self.name, "index": self.index,
                "ends": self.ends.strftime("%Y-%m-%d %H:%M UT")}


def panchanga(jd: float, latitude: float, longitude: float,
              ayanamsa: str = "LAHIRI") -> dict:
    """The five limbs in force, reckoned from the sunrise that opens the day."""
    rise, sset = sun_times(jd, latitude, longitude)

    # Traditional reckoning: the day's limbs are those standing at sunrise.
    t = _tithi_index(rise, ayanamsa)
    paksha = "Shukla" if t < 15 else "Krishna"
    within = t % 15
    tithi_name = (TITHI_NAMES[within] if within < 14
                  else ("Purnima" if paksha == "Shukla" else "Amavasya"))

    weekday = int(rise + 1.5) % 7
    sanskrit, english, lord = VARA_NAMES[weekday]

    nak = _nakshatra_index(rise, ayanamsa)
    yoga = _yoga_index(rise, ayanamsa)
    kar = _karana_index(rise, ayanamsa)

    # Rahu Kaal: daylight split into eight, one part inauspicious by weekday.
    part = (sset - rise) / 8
    n = RAHU_KAAL_PART[weekday]
    rahu_start = rise + (n - 1) * part

    return {
        "reckoned_from_sunrise": dasha.jd_to_datetime(rise).strftime(
            "%Y-%m-%d %H:%M UT"),
        "sunrise": dasha.jd_to_datetime(rise).strftime("%Y-%m-%d %H:%M UT"),
        "sunset": dasha.jd_to_datetime(sset).strftime("%Y-%m-%d %H:%M UT"),
        "tithi": {**Limb(f"{paksha} {tithi_name}", t,
                         dasha.jd_to_datetime(
                             _ends_at(rise, _tithi_index, ayanamsa))).as_dict(),
                  "paksha": paksha},
        "vara": {"name": sanskrit, "english": english, "lord": lord},
        "nakshatra": Limb(ephemeris.NAKSHATRAS[nak], nak,
                          dasha.jd_to_datetime(
                              _ends_at(rise, _nakshatra_index, ayanamsa))).as_dict(),
        "yoga": Limb(YOGA_NAMES[yoga], yoga,
                     dasha.jd_to_datetime(
                         _ends_at(rise, _yoga_index, ayanamsa))).as_dict(),
        "karana": Limb(karana_name(kar), kar,
                       dasha.jd_to_datetime(
                           _ends_at(rise, _karana_index, ayanamsa))).as_dict(),
        "rahu_kaal": {
            "from": dasha.jd_to_datetime(rahu_start).strftime("%H:%M UT"),
            "to": dasha.jd_to_datetime(rahu_start + part).strftime("%H:%M UT"),
            "note": "Traditionally avoided for starting things. One eighth of "
                    "daylight, its position set by the weekday.",
        },
    }
