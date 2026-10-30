"""Narrowing an uncertain birth time against dated life events.

The method: dasha periods shift about five days for every minute of birth
time, so across an uncertain window the period boundaries sweep across months.
If a person's real turning points cluster near where the boundaries land for
one candidate time and not the others, that candidate is better supported.

Two things this is not.

It is not proof. Dasha alignment is one technique among several, and real
rectification also uses divisional charts, transits to angles, and events the
practitioner can interrogate. This narrows candidates; it does not determine a
birth time.

It is not automatic. Nothing here writes. It returns a proposal for a person to
judge, and says plainly when the events do not discriminate at all -- which is
the common case with few events or a wide window, and is far more useful than
a confident answer drawn from noise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import confidence, dasha, ephemeris, timeplace

# A life event rarely lands exactly on a dasha boundary; this is how much slack
# to allow before the alignment stops counting for anything.
SIGMA_DAYS = 45.0

# A candidate scoring at least this share of the best one is not meaningfully
# distinguishable from it. The spread of those candidates -- not the single
# peak -- is what the birth time is actually narrowed to, and what the stored
# confidence must reflect.
PLAUSIBLE_SHARE = 0.75

# How much slack an event's own recorded date carries. A month-dated event is
# somewhere in a thirty-day span, which is two thirds of the alignment window
# on its own -- so it cannot be weighed the same as one dated to the day.
DATE_BLUR_DAYS = {"day": 0.0, "month": 15.0, "year": 182.0}

# Mahadasha changes mark bigger shifts than antardasha changes, so they carry
# more weight when an event lines up with one.
LEVEL_WEIGHT = {1: 2.0, 2: 1.0}


@dataclass
class Candidate:
    birth_time: str
    offset_minutes: float
    score: float
    lagna: str
    lagna_degrees: float
    aligned: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"birth_time": self.birth_time,
                "offset_minutes": round(self.offset_minutes, 2),
                "score": round(self.score, 3),
                "lagna": self.lagna,
                "lagna_degrees": round(self.lagna_degrees, 2),
                "aligned_events": self.aligned}


@dataclass
class Proposal:
    candidates: list[Candidate]
    best: Candidate | None
    discriminating: bool
    verdict: str
    events_used: int
    window_minutes: int
    lagna_options: list[str]
    # How far the plausible candidates actually spread, and therefore how
    # precisely the birth time may honestly be claimed to be known.
    spread_minutes: float = 0.0
    plausible_lagnas: list[str] = field(default_factory=list)
    implied_confidence: str = "VAGUE"
    # Whether the search reached a tighter confidence class than it began
    # with. False means it may still have picked the right time, but has
    # not improved on what was already known.
    precision_gained: bool = False
    # Which ascendant each stretch of the window gives, and how well each is
    # supported. When the lagna is in doubt, this is the decision to make.
    lagna_breakdown: list[dict] = field(default_factory=list)
    event_precision: dict = field(default_factory=dict)
    window_expanded: bool = False

    def as_dict(self) -> dict:
        return {"verdict": self.verdict,
                "discriminating": self.discriminating,
                "events_used": self.events_used,
                "window_minutes": self.window_minutes,
                "lagna_options": self.lagna_options,
                "spread_minutes": round(self.spread_minutes, 1),
                "plausible_lagnas": self.plausible_lagnas,
                "implied_confidence": self.implied_confidence,
                "precision_gained": self.precision_gained,
                "window_was_widened": self.window_expanded,
                "lagna_breakdown": self.lagna_breakdown,
                "event_precision": self.event_precision,
                "best": self.best.as_dict() if self.best else None,
                "candidates": [c.as_dict() for c in self.candidates],
                "note": "Nothing has been changed. If you accept a candidate, "
                        "apply it explicitly -- it is stored as a new chart "
                        "version alongside the original, never over it."}


def _boundaries(tree: dasha.DashaTree, max_level: int = 2) -> list[tuple[float, int]]:
    out = []

    def walk(periods):
        for p in periods:
            out.append((p.start_jd, p.level))
            if p.level < max_level:
                walk(p.children)

    walk(tree.periods)
    return out


def _score(tree: dasha.DashaTree, events) -> tuple[float, list[str]]:
    """How well this candidate's dasha boundaries explain the person's life."""
    bounds = _boundaries(tree)
    total, aligned = 0.0, []
    for e in events:
        try:
            y, m, d = (int(x) for x in e["happened_on"].split("-"))
        except (ValueError, AttributeError):
            continue
        event_jd = dasha.swe.julday(y, m, d, 12.0)
        best_gap, best_level = None, None
        for jd, level in bounds:
            gap = abs(jd - event_jd)
            if best_gap is None or gap < best_gap:
                best_gap, best_level = gap, level
        if best_gap is None:
            continue
        # Combine the method's own tolerance with the event's date blur, and
        # discount an event in proportion to how blurred it is. A year-dated
        # guess should nudge the answer, not steer it.
        blur = DATE_BLUR_DAYS.get(e["precision"], 15.0)
        sigma = math.hypot(SIGMA_DAYS, blur)
        weight = (LEVEL_WEIGHT.get(best_level, 1.0)
                  * (e["significance"] / 3.0)
                  * (SIGMA_DAYS / sigma))
        contribution = weight * math.exp(-((best_gap / sigma) ** 2))
        total += contribution
        if best_gap <= sigma:
            article = "a" if best_level == 1 else "an"
            level_name = "mahadasha" if best_level == 1 else "antardasha"
            # Say which tolerance the alignment was judged against. A vaguely
            # dated event is allowed a wider one, so without this a 180-day
            # gap on a year-dated guess reads exactly like a 3-day hit on a
            # date someone actually recorded.
            slack = ("" if blur == 0 else
                     f" -- within the {sigma:.0f}-day tolerance this event "
                     f"earns by being dated only to the {e['precision']}, not "
                     f"the {SIGMA_DAYS:.0f} days a day-dated event gets")
            aligned.append(f"{e['title']} ({e['happened_on']}) is "
                           f"{best_gap:.0f} days from {article} "
                           f"{level_name} change{slack}")
    return total, aligned



def _boundary_shift_per_minute(store, root, row) -> float:
    """How far the dasha boundaries move for one minute of birth time.

    Measured from this chart rather than assumed: the rate depends on which
    lord holds the birth mahadasha, and ranges from about one and a half days
    per minute to five.
    """
    y, mo, d = (int(x) for x in root["birth_date"].split("-"))
    hh, mm, ss = (int(x) for x in root["birth_time"].split(":"))
    base = datetime(y, mo, d, hh, mm, ss)
    ends: list[float] = []
    for delta in (0, 1):
        t = base + timedelta(minutes=delta)
        moment = timeplace.resolve(t.year, t.month, t.day, t.hour, t.minute,
                                   row["latitude"], row["longitude"],
                                   second=t.second)
        chart = ephemeris.compute_chart(moment.julian_day_ut, row["latitude"],
                                        row["longitude"], row["ayanamsa"])
        tree = dasha.compute(chart.get("Moon").longitude,
                             moment.julian_day_ut, levels=1)
        ends.append(tree.periods[0].end_jd)
    return abs(ends[1] - ends[0])



MAX_WINDOW_MINUTES = 720        # half a day either way; beyond that the date
                                # itself is in question, not just the time


def _scan(store, root, row, events, step_minutes, window):
    """Score candidates, widening the window if the best sits on its edge.

    A search that stops exactly where its answer is has not found the answer,
    it has found its own boundary. The original recorded time is only a guess
    when the confidence is loose, so the true fit can lie outside it.
    """
    y, mo, d = (int(x) for x in root["birth_date"].split("-"))
    hh, mm, ss = (int(x) for x in root["birth_time"].split(":"))
    base = datetime(y, mo, d, hh, mm, ss)

    while True:
        candidates: list[Candidate] = []
        offset = -window
        while offset <= window:
            t = base + timedelta(minutes=offset)
            moment = timeplace.resolve(t.year, t.month, t.day, t.hour, t.minute,
                                       row["latitude"], row["longitude"],
                                       second=t.second)
            chart = ephemeris.compute_chart(moment.julian_day_ut,
                                            row["latitude"], row["longitude"],
                                            row["ayanamsa"])
            tree = dasha.compute(chart.get("Moon").longitude,
                                 moment.julian_day_ut, levels=2)
            score, aligned = _score(tree, events)
            candidates.append(Candidate(
                birth_time=t.strftime("%H:%M:%S"), offset_minutes=offset,
                score=score, lagna=chart.ascendant.sign_english,
                lagna_degrees=chart.ascendant.degrees_in_sign, aligned=aligned))
            offset += step_minutes

        best = max(candidates, key=lambda c: c.score)
        at_edge = abs(abs(best.offset_minutes) - window) <= step_minutes
        if not at_edge or window >= MAX_WINDOW_MINUTES:
            return candidates, window
        window = min(window * 2, MAX_WINDOW_MINUTES)


def rectify(store, person_id: int, step_minutes: float = 2.0,
            window_minutes: int | None = None) -> Proposal:
    """Test candidate birth times against the life events on record."""
    row = store.active_chart_row(person_id)
    events = [dict(e) for e in store.life_events(person_id)]

    # Size the search from the ORIGINAL uncertainty, not the current one.
    # A rectified chart carries a narrow confidence precisely because this
    # ran; sizing the window from that would search only the range the last
    # answer already picked, and confirm itself forever.
    versions = {r["id"]: r for r in store.chart_versions(person_id)}
    root = row
    seen = set()
    while root["derived_from_id"] and root["derived_from_id"] in versions:
        if root["id"] in seen:
            break                       # guard against a cycle in the chain
        seen.add(root["id"])
        root = versions[root["derived_from_id"]]
    conf = confidence.TimeConfidence[root["time_confidence"]]
    window = window_minutes if window_minutes is not None else conf.window_minutes

    if len(events) < 3:
        return Proposal(
            candidates=[], best=None, discriminating=False, events_used=len(events),
            window_minutes=window, lagna_options=[],
            verdict=f"Only {len(events)} dated life events are on record. "
                    f"Rectification needs several -- five to ten, ideally "
                    f"marked for significance -- before it can distinguish one "
                    f"candidate time from another. Collect those first.")

    y, mo, d = (int(x) for x in root["birth_date"].split("-"))
    hh, mm, ss = (int(x) for x in root["birth_time"].split(":"))
    base = datetime(y, mo, d, hh, mm, ss)

    candidates, window = _scan(store, root, row, events, step_minutes, window)
    expanded = window > (window_minutes if window_minutes is not None
                         else conf.window_minutes)

    candidates.sort(key=lambda c: c.score, reverse=True)
    best = candidates[0]
    scores = [c.score for c in candidates]
    mean = sum(scores) / len(scores)
    spread = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5

    # If the best candidate is not clearly above the pack, the events simply do
    # not distinguish these times, and saying so is the honest result.
    discriminating = spread > 1e-9 and (best.score - mean) > 1.5 * spread
    lagna_options = sorted({c.lagna for c in candidates})

    # The peak is not the answer; the range of candidates indistinguishable
    # from the peak is. Stamping a fixed confidence on the winner overstates
    # what the events established.
    plausible = [c for c in candidates if c.score >= best.score * PLAUSIBLE_SHARE]
    offsets = [c.offset_minutes for c in plausible]
    measured = (max(offsets) - min(offsets)) / 2 if offsets else float(window)
    plausible_lagnas = sorted({c.lagna for c in plausible})

    # Ranking the times is not the same as narrowing them. A smooth hump over
    # the window puts one candidate above the mean while leaving a band of
    # indistinguishable neighbours as wide as the search itself -- and calling
    # that "clearly above the alternatives" invites someone to adopt a time the
    # events never established. Require that the plausible band actually be
    # narrower than what was searched before claiming a discriminating result.

    # The measured spread depends on how finely we sampled, which is an
    # artifact rather than evidence. There is a hard floor underneath it: an
    # event counts as aligned within SIGMA_DAYS of a boundary, and boundaries
    # move at a known rate per minute of birth time, so the method cannot
    # resolve finer than the kernel allows however densely it is sampled.
    shift_per_minute = _boundary_shift_per_minute(store, root, row)
    sharpest = min((math.hypot(SIGMA_DAYS, DATE_BLUR_DAYS.get(e["precision"], 15.0))
                    for e in events), default=SIGMA_DAYS)
    floor = sharpest / shift_per_minute if shift_per_minute > 0 else measured
    spread_minutes = max(measured + step_minutes / 2, floor)

    # Take the loosest confidence the spread actually supports, and never
    # claim EXACT: a rectified time is an inference, not a record.
    implied = "VAGUE"
    for level in confidence.TimeConfidence:
        if level is confidence.TimeConfidence.EXACT:
            continue
        if spread_minutes <= level.window_minutes:
            implied = level.name
            break

    # Separating the candidates and narrowing the birth time are two different
    # results, and only the first is what `discriminating` means. The second
    # has a hard ceiling: the spread cannot fall below the method's resolution
    # floor, so a search that starts from an already-tight confidence can pick
    # the right time and still buy no precision at all. Saying which happened
    # keeps a correct-but-useless answer from reading like a reason to replace
    # a time someone actually remembers.
    narrowed = (confidence.TimeConfidence[implied].window_minutes
                < conf.window_minutes)

    if discriminating and narrowed:
        verdict = (
            f"{best.birth_time} fits the recorded events best, "
            f"{best.offset_minutes:+.0f} minutes from the time on file, and it "
            f"stands clearly above the alternatives. It aligns "
            f"{len(best.aligned)} of {len(events)} events with a dasha change. "
            f"Treat this as a candidate to test against further events, not a "
            f"settled answer.")
    elif discriminating:
        verdict = (
            f"{best.birth_time} fits the recorded events best, "
            f"{best.offset_minutes:+.0f} minutes from the time on file, and it "
            f"does stand above the alternatives -- it aligns "
            f"{len(best.aligned)} of {len(events)} events with a dasha change. "
            f"But it buys no precision. The candidates indistinguishable from "
            f"it spread across +/-{spread_minutes:.0f} minutes, which is still "
            f"{implied.replace('_', ' ').lower()} -- the same class the search "
            f"started from. That is this method's resolution floor rather than "
            f"a shortage of events, so more of them will not lift it. Treat "
            f"this as corroboration of a time already known, never as grounds "
            f"to replace one.")
    else:
        verdict = (
            f"The events on record do not distinguish between these times. The "
            f"best candidate scores {best.score:.2f} against an average of "
            f"{mean:.2f}, which is inside the noise. More events, or events "
            f"dated more precisely, would be needed. Do not adopt a birth time "
            f"on this basis.")

    if len(lagna_options) > 1:
        verdict += (f" Note that the window spans more than one lagna "
                    f"({', '.join(lagna_options)}), so the candidates are not "
                    f"variations on one chart -- they are different charts.")

    by_lagna: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_lagna.setdefault(c.lagna, []).append(c)
    lagna_breakdown = []
    for name, group in by_lagna.items():
        group.sort(key=lambda c: c.offset_minutes)
        top = max(group, key=lambda c: c.score)
        lagna_breakdown.append({
            "lagna": name,
            "from": group[0].birth_time,
            "to": group[-1].birth_time,
            "best_score": round(top.score, 2),
            "best_at": top.birth_time,
            "share_of_best": round(top.score / best.score, 2) if best.score else 0.0,
        })
    lagna_breakdown.sort(key=lambda d: d["best_score"], reverse=True)

    if expanded:
        verdict += (f" The best fit lay outside the window the recorded time "
                    f"implied, so the search was widened to +/-{window} minutes. "
                    f"Treat the original time as a rough note rather than a "
                    f"starting point.")
    if len(plausible_lagnas) > 1:
        verdict += (f" The plausible candidates do not even agree on the "
                    f"ascendant ({', '.join(plausible_lagnas)}), so the choice "
                    f"between them decides which chart this person has. Do not "
                    f"treat the winner as settled.")

    return Proposal(candidates=candidates[:12], best=best,
                    discriminating=discriminating, verdict=verdict,
                    events_used=len(events), window_minutes=window,
                    lagna_options=lagna_options,
                    spread_minutes=spread_minutes,
                    plausible_lagnas=plausible_lagnas,
                    implied_confidence=implied,
                    lagna_breakdown=lagna_breakdown,
                    event_precision={
                        p: sum(1 for e in events if e["precision"] == p)
                        for p in ("day", "month", "year")},
                    window_expanded=expanded)
