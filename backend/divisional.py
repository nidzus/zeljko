"""Divisional charts, each by its own rule.

There is no single formula. Every varga divides the sign into equal parts, but
where the count STARTS differs: the navamsa runs continuously through the
zodiac, the dasamsa counts from the sign itself in odd signs and from the ninth
in even ones, the hora yields only Cancer or Leo, the trimsamsa has unequal
divisions and never yields either.

Applying one formula to all of them is a real trap, and this project fell into
it: the previous code used the continuous navamsa rule everywhere, which for
the D-60 made the rasi cancel out entirely -- every sign gave the same answer.
It went unnoticed because the confidence gate refuses the D-60 on nearly every
chart, so the wrong output was never seen.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ephemeris

# Divisional charts, and what each is traditionally read for.
VARGAS = {
    1: ("Rasi", "the life as a whole"),
    2: ("Hora", "wealth and resources"),
    3: ("Drekkana", "siblings, courage, initiative"),
    4: ("Chaturthamsa", "property, home, fixed assets"),
    7: ("Saptamsa", "children and progeny"),
    9: ("Navamsa", "marriage, and how a placement really behaves"),
    10: ("Dasamsa", "career, standing, what you are known for"),
    12: ("Dwadasamsa", "parents and inheritance"),
    30: ("Trimsamsa", "misfortune and where harm comes from"),
    60: ("Shashtiamsa", "the finest division; needs a birth time to the second"),
}

CANCER, LEO = 3, 4

# Trimsamsa: unequal spans, and the sign each maps to. Odd and even signs run
# the sequence in opposite directions, and neither ever yields Cancer or Leo --
# the luminaries own no trimsamsa.
TRIMSAMSA_ODD = [(5, 0), (10, 10), (18, 8), (25, 2), (30, 6)]      # Ar Aq Sg Ge Li
TRIMSAMSA_EVEN = [(5, 1), (12, 5), (20, 11), (25, 9), (30, 7)]     # Ta Vi Pi Cp Sc


def varga_sign(longitude: float, varga: int) -> int:
    """Which sign a longitude falls in, in the given divisional chart."""
    if varga not in VARGAS:
        raise ValueError(f"unsupported varga D-{varga}; have "
                         f"{sorted(VARGAS)}")
    longitude %= 360.0
    rasi = int(longitude // 30)
    degrees = longitude - rasi * 30
    odd = rasi % 2 == 0          # Aries is the first odd sign

    if varga == 1:
        return rasi
    if varga == 2:
        # Only ever Leo or Cancer: the Sun's hora and the Moon's.
        first_half = degrees < 15
        return (LEO if first_half else CANCER) if odd else \
               (CANCER if first_half else LEO)
    if varga == 30:
        table = TRIMSAMSA_ODD if odd else TRIMSAMSA_EVEN
        return next(sign for limit, sign in table if degrees < limit)

    part = int(degrees / (30.0 / varga))
    if varga == 3:
        return (rasi + 4 * part) % 12          # same, 5th, 9th
    if varga == 4:
        return (rasi + 3 * part) % 12          # same, 4th, 7th, 10th
    if varga == 7:
        return (rasi + part) % 12 if odd else (rasi + 6 + part) % 12
    if varga == 9:
        return (rasi * 9 + part) % 12          # runs on through the zodiac
    if varga == 10:
        return (rasi + part) % 12 if odd else (rasi + 8 + part) % 12
    if varga in (12, 60):
        return (rasi + part) % 12              # counted from the sign itself
    raise ValueError(f"no rule implemented for D-{varga}")


@dataclass
class DivisionalChart:
    varga: int
    name: str
    read_for: str
    lagna: str
    positions: list[dict]

    def as_dict(self) -> dict:
        return {"varga": f"D-{self.varga}", "name": self.name,
                "read_for": self.read_for, "lagna": self.lagna,
                "positions": self.positions}


def compute(chart: ephemeris.Chart, varga: int) -> DivisionalChart:
    """Cast a divisional chart from a rasi chart."""
    name, read_for = VARGAS[varga]
    lagna_sign = varga_sign(chart.ascendant.longitude, varga)
    positions = []
    for p in chart.positions:
        sign = varga_sign(p.longitude, varga)
        positions.append({
            "body": p.name,
            "sign": ephemeris.SIGNS[sign][1],
            # Houses in a divisional are counted from that chart's own lagna.
            "house": ((sign - lagna_sign) % 12) + 1,
            "same_sign_as_rasi": sign == p.sign_index,
            # Vargottama is specifically the navamsa repeating the rasi sign.
            # The sign recurring in some other varga is worth noting but is
            # not what the term means.
            "vargottama": varga == 9 and sign == p.sign_index,
        })
    return DivisionalChart(varga=varga, name=name, read_for=read_for,
                           lagna=ephemeris.SIGNS[lagna_sign][1],
                           positions=positions)
