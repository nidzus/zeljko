"""What a chart is entitled to claim, given how well its birth time is known.

Generic rules ("D-9 needs 5 minutes") are wrong per chart: a birth mid-sign
tolerates an hour, one near a boundary tolerates seconds. So we measure this
chart, by recomputing it across the uncertainty window and seeing which
conclusions actually survive.

The advisor asks this module before making a claim. It is a gate in code, not
an instruction the model is asked to remember.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from . import dasha, divisional, ephemeris, timeplace


class TimeConfidence(Enum):
    """How well the birth time is known, and the window that implies."""

    EXACT = ("from a birth certificate or hospital record", 1)
    RECTIFIED = ("refined against dated life events", 3)
    REMEMBERED = ("a time someone remembers being told", 15)
    TO_THE_HOUR = ("known to about the hour", 30)
    VAGUE = ("a family story -- morning, evening", 180)

    def __init__(self, description: str, window_minutes: int):
        self.description = description
        self.window_minutes = window_minutes


@dataclass
class Reliability:
    window_minutes: int
    rasi_lagna_stable: bool
    nakshatra_stable: bool
    navamsa_stable: bool
    shashtiamsa_stable: bool
    dasha_drift_days: float
    rasi_lagna: str
    degrees_to_lagna_boundary: float
    # Every divisional gets its own tolerance: a D-30 slices a sign into single
    # degrees and needs a far better birth time than a D-3 does. Defaulted, so
    # it must come last in the field order.
    varga_stable: dict = field(default_factory=dict)

    @property
    def date_precision(self) -> str:
        """How precisely dasha dates may be stated."""
        d = self.dasha_drift_days
        if not self.nakshatra_stable:
            return "none"          # the dasha sequence itself is uncertain
        if d < 3:
            return "exact dates"
        if d < 31:
            return "to the week"
        if d < 120:
            return "to the month"
        if d < 400:
            return "to the season"
        return "none"

    def allows_varga(self, varga: int) -> bool:
        """Whether this birth time can support a given divisional chart."""
        if varga not in self.varga_stable:
            raise KeyError(f"no stability computed for D-{varga}")
        return self.varga_stable[varga]

    def allows(self, claim: str) -> bool:
        """Whether a class of claim rests on ground this chart can bear."""
        return {
            "house_placement": self.rasi_lagna_stable,
            "aspect": self.rasi_lagna_stable,
            "dasha_lord": self.nakshatra_stable,
            "dasha_date": self.date_precision != "none",
            "navamsa": self.navamsa_stable,
            "shashtiamsa": self.shashtiamsa_stable,
        }[claim]

    def summary(self) -> str:
        lines = [f"Birth time known to about +/-{self.window_minutes} minutes.",
                 f"  rasi lagna {self.rasi_lagna}: "
                 f"{'stable' if self.rasi_lagna_stable else 'NOT STABLE'}"
                 f" ({self.degrees_to_lagna_boundary:.2f} deg to the sign boundary)",
                 f"  Moon nakshatra / dasha lord: "
                 f"{'stable' if self.nakshatra_stable else 'NOT STABLE'}",
                 f"  navamsa (D-9) lagna: "
                 f"{'usable' if self.navamsa_stable else 'unusable'}",
                 f"  shashtiamsa (D-60) lagna: "
                 f"{'usable' if self.shashtiamsa_stable else 'unusable'}",
                 f"  dasha dates drift up to {self.dasha_drift_days:.1f} days"
                 f" -> may be stated {self.date_precision}"]
        return "\n".join(lines)


def _facts(year, month, day, hour, minute, offset_min, lat, lon, ayanamsa):
    # Offsets can be fractional minutes, and shifting can cross midnight, so
    # let datetime do the arithmetic rather than juggling hours and minutes.
    t = datetime(year, month, day, hour, minute) + timedelta(minutes=offset_min)
    m = timeplace.resolve(t.year, t.month, t.day, t.hour, t.minute,
                          lat, lon, second=t.second)
    c = ephemeris.compute_chart(m.julian_day_ut, lat, lon, ayanamsa)
    asc, moon = c.ascendant.longitude, c.get("Moon").longitude
    tree = dasha.compute(moon, m.julian_day_ut, levels=1)
    facts = {
        "lagna": int(asc // 30),
        "nak": int(moon // dasha.NAK_ARC),
        "maha_end": tree.periods[0].end_jd,
        "lagna_deg": asc,
    }
    # The divisional lagna is what moves fastest, so each varga is tested on
    # its own rather than inferred from the navamsa.
    for varga in divisional.VARGAS:
        facts[f"v{varga}"] = divisional.varga_sign(asc, varga)
    return facts


def assess(
    year: int, month: int, day: int, hour: int, minute: int,
    latitude: float, longitude: float,
    confidence: TimeConfidence,
    ayanamsa: str = "LAHIRI",
) -> Reliability:
    """Recompute the chart across the uncertainty window; report what survives."""
    w = confidence.window_minutes
    step = max(0.25, w / 30)
    offsets, x = [], -w
    while x <= w:
        offsets.append(x)
        x += step

    samples = [_facts(year, month, day, hour, minute, o, latitude, longitude, ayanamsa)
               for o in offsets]
    base = _facts(year, month, day, hour, minute, 0, latitude, longitude, ayanamsa)

    same = lambda k: all(s[k] == base[k] for s in samples)
    drift = max(abs(s["maha_end"] - base["maha_end"]) for s in samples)

    deg_in_sign = base["lagna_deg"] % 30
    to_boundary = min(deg_in_sign, 30 - deg_in_sign)

    varga_stable = {v: same(f"v{v}") for v in divisional.VARGAS}
    return Reliability(
        window_minutes=w,
        rasi_lagna_stable=same("lagna"),
        nakshatra_stable=same("nak"),
        navamsa_stable=varga_stable[9],
        shashtiamsa_stable=varga_stable[60],
        varga_stable=varga_stable,
        dasha_drift_days=drift,
        rasi_lagna=ephemeris.SIGNS[base["lagna"]][1],
        degrees_to_lagna_boundary=to_boundary,
    )
