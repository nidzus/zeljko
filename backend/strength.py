"""How strong each graha is, and how good a transit is for this chart.

This exists to help resolve conflicts. Several factors will point different
ways in any real question, and the advisor has to commit to a reading rather
than list contradictions. Weighing them needs to know which graha can actually
deliver -- an exalted Jupiter aspecting the 10th means something a combust,
debilitated one does not.

Everything here is classical and deterministic. Where a value is disputed
between schools, it is named as such rather than silently picked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ephemeris

# Sign indices: 0 Mesha (Aries) .. 11 Meena (Pisces)
ARIES, TAURUS, GEMINI, CANCER, LEO, VIRGO = 0, 1, 2, 3, 4, 5
LIBRA, SCORPIO, SAGITTARIUS, CAPRICORN, AQUARIUS, PISCES = 6, 7, 8, 9, 10, 11

# Exaltation sign and the exact degree of deepest exaltation. Debilitation is
# the opposite sign at the same degree.
EXALTATION = {
    "Sun": (ARIES, 10), "Moon": (TAURUS, 3), "Mars": (CAPRICORN, 28),
    "Mercury": (VIRGO, 15), "Jupiter": (CANCER, 5), "Venus": (PISCES, 27),
    "Saturn": (LIBRA, 20),
    # The nodes' exaltations are disputed; Taurus/Scorpio is the common reading.
    "Rahu": (TAURUS, 20), "Ketu": (SCORPIO, 20),
}

OWN_SIGNS = {
    "Sun": [LEO], "Moon": [CANCER], "Mars": [ARIES, SCORPIO],
    "Mercury": [GEMINI, VIRGO], "Jupiter": [SAGITTARIUS, PISCES],
    "Venus": [TAURUS, LIBRA], "Saturn": [CAPRICORN, AQUARIUS],
}

# Sign, and the degree span within it.
MOOLATRIKONA = {
    "Sun": (LEO, 0, 20), "Moon": (TAURUS, 4, 30), "Mars": (ARIES, 0, 12),
    "Mercury": (VIRGO, 16, 20), "Jupiter": (SAGITTARIUS, 0, 10),
    "Venus": (LIBRA, 0, 15), "Saturn": (AQUARIUS, 0, 20),
}

SIGN_LORD = {
    ARIES: "Mars", TAURUS: "Venus", GEMINI: "Mercury", CANCER: "Moon",
    LEO: "Sun", VIRGO: "Mercury", LIBRA: "Venus", SCORPIO: "Mars",
    SAGITTARIUS: "Jupiter", CAPRICORN: "Saturn", AQUARIUS: "Saturn",
    PISCES: "Jupiter",
}

# Naisargika maitri: permanent friendship, independent of any chart.
NATURAL_FRIENDS = {
    "Sun": {"Moon", "Mars", "Jupiter"},
    "Moon": {"Sun", "Mercury"},
    "Mars": {"Sun", "Moon", "Jupiter"},
    "Mercury": {"Sun", "Venus"},
    "Jupiter": {"Sun", "Moon", "Mars"},
    "Venus": {"Mercury", "Saturn"},
    "Saturn": {"Mercury", "Venus"},
}
NATURAL_ENEMIES = {
    "Sun": {"Venus", "Saturn"},
    "Moon": set(),
    "Mars": {"Mercury"},
    "Mercury": {"Moon"},
    "Jupiter": {"Mercury", "Venus"},
    "Venus": {"Sun", "Moon"},
    "Saturn": {"Sun", "Moon", "Mars"},
}

# How close to the Sun a graha must come to be burnt up. Mercury and Venus
# have tighter orbs when retrograde.
COMBUSTION_ORB = {"Moon": 12.0, "Mars": 17.0, "Mercury": 14.0,
                  "Jupiter": 11.0, "Venus": 10.0, "Saturn": 15.0}
COMBUSTION_ORB_RETROGRADE = {"Mercury": 12.0, "Venus": 8.0}

# Digbala: the house in which each graha has full directional strength.
DIG_BALA_HOUSE = {"Jupiter": 1, "Mercury": 1, "Sun": 10, "Mars": 10,
                  "Saturn": 7, "Moon": 4, "Venus": 4}


@dataclass
class Strength:
    body: str
    sign: str
    house: int
    dignity: str
    dignity_note: str
    combust: bool
    combust_note: str
    retrograde: bool
    dig_bala: bool
    vargottama: bool
    verdict: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"body": self.body, "sign": self.sign, "house": self.house,
                "dignity": self.dignity, "dignity_note": self.dignity_note,
                "combust": self.combust, "combust_note": self.combust_note,
                "retrograde": self.retrograde, "digbala": self.dig_bala,
                "vargottama": self.vargottama,
                "verdict": self.verdict, "reasons": self.reasons}


def _dignity(body: str, sign: int, degrees: float) -> tuple[str, str]:
    if body in EXALTATION:
        ex_sign, ex_deg = EXALTATION[body]
        if sign == ex_sign:
            gap = abs(degrees - ex_deg)
            close = " (near its exact degree)" if gap < 3 else ""
            return "exalted", f"exalted in {ephemeris.SIGNS[sign][1]}{close}"
        if sign == (ex_sign + 6) % 12:
            gap = abs(degrees - ex_deg)
            close = " (near its exact degree)" if gap < 3 else ""
            return "debilitated", f"debilitated in {ephemeris.SIGNS[sign][1]}{close}"

    if body in MOOLATRIKONA:
        mt_sign, lo, hi = MOOLATRIKONA[body]
        if sign == mt_sign and lo <= degrees < hi:
            return "moolatrikona", f"in its moolatrikona portion of " \
                                   f"{ephemeris.SIGNS[sign][1]}"

    if sign in OWN_SIGNS.get(body, []):
        return "own sign", f"in its own sign {ephemeris.SIGNS[sign][1]}"

    lord = SIGN_LORD[sign]
    if lord == body:
        return "own sign", f"in its own sign {ephemeris.SIGNS[sign][1]}"
    if body in NATURAL_FRIENDS:
        if lord in NATURAL_FRIENDS[body]:
            return "friendly", f"in {ephemeris.SIGNS[sign][1]}, a sign of its " \
                               f"friend {lord}"
        if lord in NATURAL_ENEMIES[body]:
            return "inimical", f"in {ephemeris.SIGNS[sign][1]}, a sign of its " \
                               f"enemy {lord}"
        return "neutral", f"in {ephemeris.SIGNS[sign][1]}, a neutral sign"
    return "neutral", f"in {ephemeris.SIGNS[sign][1]}"


def _combustion(body: str, longitude: float, sun_longitude: float,
                retrograde: bool) -> tuple[bool, str]:
    if body in ("Sun", "Rahu", "Ketu"):
        return False, ""
    orb = COMBUSTION_ORB.get(body)
    if orb is None:
        return False, ""
    if retrograde and body in COMBUSTION_ORB_RETROGRADE:
        orb = COMBUSTION_ORB_RETROGRADE[body]
    separation = abs((longitude - sun_longitude + 180) % 360 - 180)
    if separation <= orb:
        return True, (f"combust: {separation:.1f} degrees from the Sun, "
                      f"inside its {orb:.0f} degree orb. Its significations are "
                      f"burnt up and it cannot deliver on its own.")
    if separation <= orb * 1.5:
        return False, (f"{separation:.1f} degrees from the Sun -- clear of "
                       f"combustion but not by much.")
    return False, ""


def assess(chart: ephemeris.Chart) -> list[Strength]:
    """Weigh every graha in a chart."""
    sun = chart.get("Sun")
    out = []
    for p in chart.positions:
        dignity, note = _dignity(p.name, p.sign_index, p.degrees_in_sign)
        combust, cnote = _combustion(p.name, p.longitude, sun.longitude,
                                     p.retrograde)
        dig = DIG_BALA_HOUSE.get(p.name) == p.house
        # Vargottama: the same sign in the rasi chart and the navamsa. A
        # classical mark of a placement holding up under pressure.
        navamsa_sign = int(p.longitude / (30 / 9)) % 12
        vargottama = navamsa_sign == p.sign_index

        # The dignity is always worth stating, including when it is neutral --
        # "nothing special here" is information the advisor needs in order to
        # weigh a factor down rather than silently omit it.
        score, reasons = {"exalted": 2, "moolatrikona": 2, "own sign": 2,
                          "friendly": 1, "neutral": 0, "inimical": -1,
                          "debilitated": -2}[dignity], [note]

        if combust:
            score -= 2; reasons.append(cnote)
        elif cnote:
            reasons.append(cnote)
        if dig:
            score += 1
            reasons.append(f"in the {p.house}th house, where it has full "
                           f"directional strength")
        if vargottama:
            score += 1
            reasons.append("vargottama: the same sign in the rasi and the "
                           "navamsa, so the placement holds up")
        if p.retrograde and p.name not in ("Rahu", "Ketu"):
            reasons.append("retrograde, which classical opinion divides on: "
                           "some read it as strengthened, others as turned "
                           "inward and delayed in effect")

        verdict = ("strong" if score >= 2 else "weak" if score <= -2
                   else "moderate")
        out.append(Strength(
            body=p.name, sign=p.sign_english, house=p.house, dignity=dignity,
            dignity_note=note, combust=combust, combust_note=cnote,
            retrograde=p.retrograde, dig_bala=dig, vargottama=vargottama,
            verdict=verdict, reasons=reasons))
    return out


# ----------------------------------------------------------- ashtakavarga

# Ashtakavarga answers the question a generic rule cannot: is this transit good
# FOR THIS CHART. Each of eight reference points contributes a bindu to certain
# houses counted from itself; the total in a sign is how supportive that sign is
# when a graha transits it.
#
# The tables have published row totals -- Sun 48, Moon 49, Mars 39, Mercury 54,
# Jupiter 56, Venus 52, Saturn 39, summing to 337. verify_strength.py checks
# every row against those, so a mistranscribed table fails loudly rather than
# quietly skewing every transit judgement.
CONTRIBUTORS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus",
                "Saturn", "Lagna"]

ASHTAKAVARGA = {
    "Sun": {
        "Sun": [1, 2, 4, 7, 8, 9, 10, 11], "Moon": [3, 6, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [3, 5, 6, 9, 10, 11, 12], "Jupiter": [5, 6, 9, 11],
        "Venus": [6, 7, 12], "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna": [3, 4, 6, 10, 11, 12]},
    "Moon": {
        "Sun": [3, 6, 7, 8, 10, 11], "Moon": [1, 3, 6, 7, 10, 11],
        "Mars": [2, 3, 5, 6, 9, 10, 11],
        "Mercury": [1, 3, 4, 5, 7, 8, 10, 11],
        "Jupiter": [1, 4, 7, 8, 10, 11, 12],
        "Venus": [3, 4, 5, 7, 9, 10, 11], "Saturn": [3, 5, 6, 11],
        "Lagna": [3, 6, 10, 11]},
    "Mars": {
        "Sun": [3, 5, 6, 10, 11], "Moon": [3, 6, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11], "Mercury": [3, 5, 6, 11],
        "Jupiter": [6, 10, 11, 12], "Venus": [6, 8, 11, 12],
        "Saturn": [1, 4, 7, 8, 9, 10, 11], "Lagna": [1, 3, 6, 10, 11]},
    "Mercury": {
        "Sun": [5, 6, 9, 11, 12], "Moon": [2, 4, 6, 8, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [1, 3, 5, 6, 9, 10, 11, 12], "Jupiter": [6, 8, 11, 12],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 11],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna": [1, 2, 4, 6, 8, 10, 11]},
    "Jupiter": {
        "Sun": [1, 2, 3, 4, 7, 8, 9, 10, 11], "Moon": [2, 5, 7, 9, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [1, 2, 4, 5, 6, 9, 10, 11],
        "Jupiter": [1, 2, 3, 4, 7, 8, 10, 11],
        "Venus": [2, 5, 6, 9, 10, 11], "Saturn": [3, 5, 6, 12],
        "Lagna": [1, 2, 4, 5, 6, 7, 9, 10, 11]},
    "Venus": {
        "Sun": [8, 11, 12], "Moon": [1, 2, 3, 4, 5, 8, 9, 11, 12],
        "Mars": [3, 5, 6, 9, 11, 12], "Mercury": [3, 5, 6, 9, 11],
        "Jupiter": [5, 8, 9, 10, 11],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 10, 11],
        "Saturn": [3, 4, 5, 8, 9, 10, 11],
        # The 11th here is easy to drop; without it the row totals 7 and the
        # whole system totals 336 instead of the classical 337.
        "Lagna": [1, 2, 3, 4, 5, 8, 9, 11]},
    "Saturn": {
        "Sun": [1, 2, 4, 7, 8, 10, 11], "Moon": [3, 6, 11],
        "Mars": [3, 5, 6, 10, 11, 12], "Mercury": [6, 8, 9, 10, 11, 12],
        "Jupiter": [5, 6, 11, 12], "Venus": [6, 11, 12],
        "Saturn": [3, 5, 6, 11], "Lagna": [1, 3, 4, 6, 10, 11]},
}

PUBLISHED_TOTALS = {"Sun": 48, "Moon": 49, "Mars": 39, "Mercury": 54,
                    "Jupiter": 56, "Venus": 52, "Saturn": 39}


def bhinnashtakavarga(chart: ephemeris.Chart, body: str) -> list[int]:
    """Bindus this graha has in each of the twelve signs, for this chart.

    Returned by sign index, 0 = Mesha.
    """
    if body not in ASHTAKAVARGA:
        raise KeyError(f"no ashtakavarga table for {body}")
    bindus = [0] * 12
    for contributor, houses in ASHTAKAVARGA[body].items():
        if contributor == "Lagna":
            base = chart.lagna_sign_index
        else:
            base = chart.get(contributor).sign_index
        for house in houses:
            bindus[(base + house - 1) % 12] += 1
    return bindus


def sarvashtakavarga(chart: ephemeris.Chart) -> list[int]:
    """The seven charts summed: overall support per sign."""
    total = [0] * 12
    for body in ASHTAKAVARGA:
        for i, b in enumerate(bhinnashtakavarga(chart, body)):
            total[i] += b
    return total


def transit_support(chart: ephemeris.Chart, body: str,
                    transiting_sign: int) -> dict:
    """How well this chart supports a given graha transiting a given sign.

    A graha crossing a sign holding 5 or more of its own bindus tends to give
    its better results there; 2 or fewer, its worse. This is per-chart, which
    is why two people meet the same transit differently.
    """
    own = bhinnashtakavarga(chart, body)[transiting_sign]
    sav = sarvashtakavarga(chart)[transiting_sign]
    if own >= 5:
        reading = "supported"
    elif own <= 2:
        reading = "poorly supported"
    else:
        reading = "mixed"
    return {
        "body": body,
        "sign": ephemeris.SIGNS[transiting_sign][1],
        "house_of_nativity": chart.house_of(transiting_sign),
        "own_bindus": own,
        "max_possible": 8,
        "sarvashtakavarga": sav,
        "reading": reading,
        "note": "Five or more of a graha's own bindus favours it in that sign; "
                "two or fewer works against it. Sarvashtakavarga above about 30 "
                "marks a generally supported sign for this chart.",
    }
