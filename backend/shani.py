"""Saturn measured from the Moon: Sade Sati and its smaller relatives.

Everything else in this project counts houses from the ascendant. This does
not, and that is the whole point -- Sade Sati is Saturn crossing the 12th, 1st
and 2nd from the natal MOON, an axis the rest of the app cannot see. A chart
can have Saturn in an unremarkable house from the lagna and be in the middle of
its hardest Saturn period.

It is also the thing people actually ask about, and the thing they most often
have half-right, so it is worth computing exactly rather than eyeballing.

On retrogression. Saturn does not cross these signs cleanly: it enters, turns
back, re-enters. Chasing ingresses gets this wrong -- it reports the last
re-entry as the start, cutting years off the period. So the span is found as a
predicate instead: Saturn is either inside the three-sign block or it is not,
and motion within the block, forwards or backwards, never leaves it.
"""
from __future__ import annotations

from dataclasses import dataclass

import swisseph as swe

from . import dasha, ephemeris, transits

# Offsets from the natal Moon, and what each is called.
SADE_SATI_OFFSETS = {12: "rising", 1: "peak", 2: "setting"}
OTHER_PERIODS = {4: "Kantaka Shani", 8: "Ashtama Shani"}

SCAN_STEP = 5.0          # days; Saturn covers about 0.17 degrees in that time
MERGE_GAP = 200.0        # days; a dip out of the block shorter than this is
                         # a retrograde wobble at the edge, not a separate period

# A period already under way when a scan begins would otherwise be reported as
# starting at the scan's own edge -- a window artifact dressed as a date. The
# real boundary is found by stepping outside the window, and cannot be further
# away than a Saturn cycle. Fifteen years is ample for any of these periods.
EDGE_LIMIT_DAYS = 365.2425 * 15


def _saturn_sign(jd: float, ayanamsa: str = "LAHIRI") -> int:
    return int(transits.state(jd, "Saturn", ayanamsa)[0] // 30)


def _offset_from_moon(sign: int, moon_sign: int) -> int:
    return ((sign - moon_sign) % 12) + 1


def _refine(lo: float, hi: float, predicate) -> float:
    while hi - lo > 0.02:
        mid = (lo + hi) / 2
        if predicate(mid) == predicate(hi):
            hi = mid
        else:
            lo = mid
    return hi


def _walk_out(predicate, jd: float, direction: int,
              limit_days: float = EDGE_LIMIT_DAYS) -> float | None:
    """The real boundary of a span that was still running at the scan's edge.

    Step outward until the predicate fails, then refine the crossing the same
    way the forward scan does. Returns None if no boundary lies within the
    limit, which for Saturn should not happen -- and when it does the period is
    reported as truncated rather than quietly given the window's edge as a date.
    """
    step = SCAN_STEP * direction
    probe, travelled = jd, 0.0
    while travelled < limit_days:
        nxt = probe + step
        travelled += SCAN_STEP
        if predicate(nxt):
            probe = nxt
            continue

        # A crossing -- but not necessarily the boundary. Saturn steps out of
        # the block and back in while retrograde, and the forward scan merges
        # such a wobble into one period. The extension has to merge it too, or
        # it reports the re-entry as the start, which is the very mistake the
        # module's docstring warns against.
        lo, hi = (nxt, probe) if direction < 0 else (probe, nxt)
        boundary = _refine(lo, hi, predicate)
        gap_probe, gap = nxt, 0.0
        while gap < MERGE_GAP and travelled + gap < limit_days:
            gap_probe += step
            gap += SCAN_STEP
            if predicate(gap_probe):
                probe, travelled = gap_probe, travelled + gap
                break
        else:
            return boundary
    return None


def _resolve_window_edges(predicate, spans, start_jd: float, end_jd: float):
    """Replace scan-window edges with the boundaries that lie beyond them.

    A caller asking what Saturn is doing over the next few decades should still
    be told correctly when the period it is in began, even if that was before
    the window opened. Without this, the answer changes every time the question
    is asked, because the reported start tracks the query date.
    """
    if not spans:
        return spans, set()
    out = [list(s) for s in spans]
    truncated = set()
    if predicate(start_jd):
        real = _walk_out(predicate, start_jd, -1)
        if real is None:
            truncated.add("start")
        else:
            out[0][0] = real
    if predicate(end_jd):
        real = _walk_out(predicate, end_jd, +1)
        if real is None:
            truncated.add("end")
        else:
            out[-1][1] = real
    return [tuple(s) for s in out], truncated


@dataclass
class Phase:
    name: str
    sign: str
    start_jd: float
    end_jd: float

    def as_dict(self) -> dict:
        return {"phase": self.name, "sign": self.sign,
                "from": dasha.jd_to_datetime(self.start_jd).strftime("%Y-%m-%d"),
                "to": dasha.jd_to_datetime(self.end_jd).strftime("%Y-%m-%d")}


@dataclass
class Period:
    kind: str                 # "Sade Sati", "Kantaka Shani", "Ashtama Shani"
    start_jd: float
    end_jd: float
    phases: list[Phase]
    # Set only when a real boundary could not be found beyond the scan window,
    # so a caller is never handed the window's edge believing it is a date.
    start_truncated: bool = False
    end_truncated: bool = False

    @property
    def years(self) -> float:
        return (self.end_jd - self.start_jd) / 365.2425

    def as_dict(self) -> dict:
        out = {"kind": self.kind,
               "from": dasha.jd_to_datetime(self.start_jd).strftime("%Y-%m-%d"),
               "to": dasha.jd_to_datetime(self.end_jd).strftime("%Y-%m-%d"),
               "years": round(self.years, 1),
               "phases": [p.as_dict() for p in self.phases]}
        if self.start_truncated or self.end_truncated:
            out["truncated"] = {"start": self.start_truncated,
                                "end": self.end_truncated,
                                "note": "A boundary lies outside the range "
                                        "searched; the date shown on that side "
                                        "is the edge of the search, not a "
                                        "computed transition."}
        return out


def _spans(predicate, start_jd: float, end_jd: float,
           merge: bool = True) -> list[tuple[float, float]]:
    """Contiguous stretches where the predicate holds.

    Merging is right for the period as a whole -- a retrograde dip out of the
    three-sign block is one period, not two. It is wrong for the phases within
    it, where Saturn genuinely does leave a sign and come back, and saying so
    is more honest than presenting overlapping intervals.
    """
    raw, jd = [], start_jd
    inside = predicate(jd)
    span_start = jd if inside else None
    while jd < end_jd:
        jd += SCAN_STEP
        now = predicate(jd)
        if now and not inside:
            span_start = _refine(jd - SCAN_STEP, jd, predicate)
        elif inside and not now:
            raw.append((span_start, _refine(jd - SCAN_STEP, jd, predicate)))
            span_start = None
        inside = now
    if inside and span_start is not None:
        raw.append((span_start, end_jd))

    # Saturn can step just outside the block and come back while retrograde.
    # That is one period, not two.
    if not merge:
        return raw
    merged: list[list[float]] = []
    for lo, hi in raw:
        if merged and lo - merged[-1][1] < MERGE_GAP:
            merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    return [(a, b) for a, b in merged]


def periods(chart: ephemeris.Chart, start_jd: float, end_jd: float,
            kind: str = "Sade Sati") -> list[Period]:
    """Every Saturn period of the given kind in the window."""
    moon_sign = chart.get("Moon").sign_index
    ayanamsa = chart.ayanamsa_name

    if kind == "Sade Sati":
        wanted = {(moon_sign + off - 1) % 12 for off in (12, 1, 2)}
    else:
        offset = next(o for o, n in OTHER_PERIODS.items() if n == kind)
        wanted = {(moon_sign + offset - 1) % 12}

    def inside(jd):
        return _saturn_sign(jd, ayanamsa) in wanted

    spans, truncated = _resolve_window_edges(
        inside, _spans(inside, start_jd, end_jd), start_jd, end_jd)

    out = []
    for index, (lo, hi) in enumerate(spans):
        phases = []
        if kind == "Sade Sati":
            for offset, label in SADE_SATI_OFFSETS.items():
                sign = (moon_sign + offset - 1) % 12
                sub = _spans(lambda jd, s=sign: _saturn_sign(jd, ayanamsa) == s,
                             lo, hi, merge=False)
                for i, (a, b) in enumerate(sub):
                    name = label if i == 0 else f"{label} (returned)"
                    phases.append(Phase(name, ephemeris.SIGNS[sign][1], a, b))
            phases.sort(key=lambda p: p.start_jd)
        out.append(Period(
            kind, lo, hi, phases,
            start_truncated=("start" in truncated and index == 0),
            end_truncated=("end" in truncated and index == len(spans) - 1)))
    return out


def status(chart: ephemeris.Chart, jd: float, look_years: float = 35.0) -> dict:
    """What Saturn is doing to this chart right now, measured from the Moon."""
    moon = chart.get("Moon")
    sign = _saturn_sign(jd, chart.ayanamsa_name)
    offset = _offset_from_moon(sign, moon.sign_index)

    running, upcoming, past = None, None, None
    for kind in ("Sade Sati", *OTHER_PERIODS.values()):
        found = periods(chart, jd - look_years * 365.2425,
                        jd + look_years * 365.2425, kind)
        for p in found:
            if p.start_jd <= jd < p.end_jd:
                running = p
            elif p.start_jd > jd and (upcoming is None
                                      or p.start_jd < upcoming.start_jd):
                if kind == "Sade Sati":
                    upcoming = p
            elif p.end_jd <= jd and kind == "Sade Sati":
                if past is None or p.end_jd > past.end_jd:
                    past = p

    result = {
        "natal_moon_sign": moon.sign_english,
        "saturn_transiting": ephemeris.SIGNS[sign][1],
        "house_from_moon": offset,
        "house_from_ascendant": chart.house_of(sign),
        "note": "Sade Sati is counted from the Moon, not the ascendant. A "
                "chart can have Saturn somewhere unremarkable from the lagna "
                "and still be in the middle of it.",
    }

    if running:
        elapsed = (jd - running.start_jd) / (running.end_jd - running.start_jd)
        phase = next((p for p in running.phases
                      if p.start_jd <= jd < p.end_jd), None)
        result["running"] = {
            **running.as_dict(),
            "phase_now": phase.name if phase else None,
            "elapsed_fraction": round(elapsed, 2),
            "remaining_years": round((running.end_jd - jd) / 365.2425, 1),
        }
    else:
        result["running"] = None
        result["reading"] = (
            f"Saturn is in the {offset}th from the Moon, which carries no named "
            f"period." if offset not in OTHER_PERIODS else "")

    if past:
        result["last_sade_sati"] = past.as_dict()
    if upcoming:
        result["next_sade_sati"] = {
            **upcoming.as_dict(),
            "years_away": round((upcoming.start_jd - jd) / 365.2425, 1),
        }
    return result
