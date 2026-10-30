"""Exposes the advisor's tools over MCP, so Claude Code or the Claude desktop
app can be the interface.

This is the same gated tool layer the in-app advisor uses. The gate, the
refusals, and the date rounding all behave identically -- the only difference
is that the conversation happens in Claude's window rather than ours, and runs
on your existing subscription instead of per-token billing.

Memory is the point. Beyond reading the chart, these tools read and write your
decision journal and life events, so advice accumulates instead of starting
from nothing every session.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import tools
from .advisor import SYSTEM_RULES
from .store import Store

INSTRUCTIONS = SYSTEM_RULES + """

USING THESE TOOLS

Start by calling chart_context. It returns the nativity, the life events on
record, and -- importantly -- which kinds of claim this birth time can support.
Do not skip it; without it you are guessing at a chart you cannot see.

Call past_decisions before answering anything substantive. If this question has
been asked before, say so and say what happened. That continuity is the whole
reason these tools exist rather than the person simply describing their chart
to you in a fresh conversation.

Tool results are visible to the person you are advising, so you do not need
bracketed fact ids. Still name which result a claim rests on whenever it is not
obvious from context.

When the conversation reaches an actual judgement, call record_decision. If you
do not, it is not saved, and the next conversation starts blind again. Record it
even when the answer is "wait" -- especially then, since the point is to check
later whether waiting was right.

If the person tells you something dated that happened to them, call
add_life_event. Those entries are what any future birth-time rectification is
tested against, so they are worth capturing even in passing.

Two tools decide which scale a question lives at. panchanga_for is the day
scale: tithi, weekday, nakshatra, yoga, karana, and Rahu Kaal. Reach for it
only when the question is about a day or a week; on a career or relocation
question nothing in it moves.

Never call a day good or bad from panchanga_for alone. The panchanga is the
same for everyone standing in the same place; personal_day is counted from
this person's natal Moon and routinely disagrees with it. Check both.

If someone describes a long heavy stretch of years, or asks about Sade Sati,
call saturn_from_moon. It is measured from the Moon, so transits_at cannot
see it and will miss it entirely.

Before calling any transit good or bad, call transit_support. Ashtakavarga is
the classical reason two people meet the same transit differently, and a
generic reading will be wrong for roughly half of charts. graha_strength is
what lets you weigh conflicting factors rather than average them.

For questions about the shape of a life rather than a moment in it, call
yogas_in_chart. Detecting combinations in code keeps a chart's reading stable
between sessions instead of depending on what you happen to notice.

If a birth time is loose and there are life events on record,
propose_rectification can narrow it. Put the result to the person; never adopt
a candidate yourself, and never call apply_rectification without their explicit
agreement.
"""

mcp = MCPServer(
    name="jyotisha",
    title="Jyotisha advisor",
    instructions=INSTRUCTIONS,
)

# Every tool, in order, so the shared server (backend/remote.py) can offer the
# same set over HTTP without a second list to keep in step.
TOOLS: list = []


def tool(fn):
    TOOLS.append(fn)
    return mcp.tool()(fn)


# Run locally, this is a single-user process with one long-lived connection,
# acting as the owner of the personal database. Keeping the runners alive
# keeps fact ids stable for a session.
_store: Store | None = None
_runners: dict[tuple[int, int], tools.ToolRunner] = {}

# Set by backend/remote.py when this process is the shared server. From then
# on there is no local store at all: each call gets the store of the account
# that signed in, and a call with no valid sign-in gets an error and nothing
# else. Tools never choose an account themselves.
_session_store = None


def _get_store() -> Store:
    global _store
    if _session_store is not None:
        return _session_store()
    if _store is None:
        _store = Store()
    return _store


def forget_account(account_id: int) -> None:
    """Drop what is cached for an account, so its key leaves memory."""
    for cached in [k for k in _runners if k[0] == account_id]:
        del _runners[cached]


def _resolve(person_id: int | str | None) -> int:
    """Which profile a call is about.

    Accepts an id or a name, because in conversation people are named, not
    numbered. Falls back to the only profile when there is just one.

    Only ever looks among the caller's own profiles: store.people() is
    already limited to their account. An id that belongs to someone else gets
    the same answer as an id that does not exist.
    """
    store = _get_store()
    people = store.people()
    # ToolError is the one exception type MCP passes through to the client.
    # A plain ValueError is replaced with "Error executing tool", which would
    # hide exactly the guidance a first-time caller needs.
    if not people:
        raise ToolError(
            "No profiles yet. Call create_profile to set one up -- ask for "
            "name, birth date, local birth time, birthplace, and how well "
            "the time is known. search_places finds coordinates by city; "
            "parse_coordinates reads a pasted Google Maps location.")
    if isinstance(person_id, str) and not person_id.isdigit():
        wanted = person_id.strip().lower()
        exact = [p for p in people if p["name"].lower() == wanted]
        partial = [p for p in people if wanted in p["name"].lower()]
        hits = exact or partial
        if len(hits) == 1:
            return hits[0]["id"]
        if not hits:
            raise ToolError(
                f"No profile named {person_id!r}. Available: "
                + ", ".join(p["name"] for p in people))
        raise ToolError(
            f"{person_id!r} matches more than one profile: "
            + ", ".join(p["name"] for p in hits))
    if person_id is not None:
        if any(p["id"] == int(person_id) for p in people):
            return int(person_id)
        raise ToolError(
            f"No profile with id {person_id}. Available: "
            + ", ".join(p["name"] for p in people))
    if len(people) == 1:
        return people[0]["id"]
    listing = ", ".join(p["name"] for p in people)
    raise ToolError(f"Several profiles exist. Say whose chart this is -- pass person_id as a name. Available: {listing}")


def _runner(person_id: int) -> tools.ToolRunner:
    store = _get_store()
    cached = (store.account_id, person_id)
    if cached not in _runners:
        _runners[cached] = tools.ToolRunner(store, person_id)
    return _runners[cached]


def _decision(decision_id: int) -> int:
    """A decision id the caller owns, or the error a missing one gets."""
    try:
        return _get_store().decision(decision_id)["id"]
    except KeyError:
        raise ToolError(
            f"No decision with id {decision_id}. past_decisions lists the "
            f"ones on record.") from None


# ------------------------------------------------------------------ reading


@tool
def list_people() -> list[dict]:
    """Every profile you have, with its id and lagna."""
    store = _get_store()
    out = []
    for p in store.people():
        try:
            chart = store.compute(store.active_chart_row(p["id"]))
            lagna = chart.ascendant.sign_english
        except KeyError:
            lagna = None
        out.append({"person_id": p["id"], "name": p["name"],
                    "relation": p["relation"], "lagna": lagna})
    return out


@tool
def chart_context(person_id: int | str | None = None) -> str:
    """The nativity, the life events on record, and which claims the birth time
    supports. Call this first."""
    return _get_store().context_prefix(_resolve(person_id))


@tool
def dasha_at(date: str, person_id: int | str | None = None) -> dict:
    """Vimshottari periods running at a date, nested three deep. Dates come back
    only as precisely as the birth time supports."""
    return _runner(_resolve(person_id)).dasha_at(date=date)


@tool
def transits_at(date: str, person_id: int | str | None = None) -> dict:
    """Where each graha is transiting at a date, and which house of this
    nativity it occupies, with degree in sign and retrogression."""
    return _runner(_resolve(person_id)).transits_at(date=date)


@tool
def events_between(start: str, end: str, bodies: list[str] | None = None,
                   person_id: int | str | None = None) -> dict:
    """Every moment between two dates where this nativity's situation changes:
    ingresses with the house entered, stations, and dasha handovers."""
    return _runner(_resolve(person_id)).events_between(
        start=start, end=end, bodies=bodies)


@tool
def divisional_chart(varga: int, person_id: int | str | None = None) -> dict:
    """A divisional chart, each read for its own area of life.

    10 is the dasamsa -- career and standing, the one to reach for on a work
    question. 9 the navamsa: marriage, and how a placement really behaves
    under pressure. 4 property, 7 children, 3 siblings and initiative, 2
    wealth, 12 parents, 30 misfortune, 60 the finest division.

    Each has its own tolerance, checked against this birth time. A refusal is
    common and is not an error -- say what would fix it instead.
    """
    return _runner(_resolve(person_id)).divisional_chart(varga=varga)


@tool
def past_decisions(person_id: int | str | None = None, limit: int = 20) -> list[dict]:
    """Questions asked before, what was advised, what was chosen, and how it
    turned out. Read this before answering anything substantive."""
    store = _get_store()
    rows = store.decisions(_resolve(person_id))[-limit:]
    return [{"decision_id": r["id"], "asked_at": r["asked_at"],
             "question": r["question"], "question_type": r["question_type"],
             "verdict": r["verdict"], "confidence": r["confidence"],
             "window": [r["window_opens"], r["window_closes"]],
             "chose": r["chose"], "outcome": r["outcome"],
             "outcome_rating": r["outcome_rating"]} for r in rows]


# ------------------------------------------------------------------ writing


@tool
def record_decision(question: str, verdict: str,
                    question_type: str | None = None,
                    confidence_note: str = "",
                    window_opens: str | None = None,
                    window_closes: str | None = None,
                    relied_on: list[str] | None = None,
                    person_id: int | str | None = None) -> dict:
    """Save a judgement to the decision journal.

    Call this whenever the conversation reaches an actual answer. `relied_on`
    is a short list of the facts the verdict rests on, in your own words.
    """
    pid = _resolve(person_id)
    store = _get_store()
    runner = _runner(pid)
    decision_id = store.record_decision(
        pid, runner.row["id"], question, question_type=question_type,
        verdict=verdict, confidence_note=confidence_note,
        window_opens=window_opens, window_closes=window_closes,
        reliability_snapshot={
            "date_precision": runner.reliability.date_precision,
            "window_minutes": runner.reliability.window_minutes,
        })
    for claim in relied_on or []:
        store.add_citation(decision_id, claim, "cited", {"stated": claim})
    return {"decision_id": decision_id,
            "saved": "Recorded. Ask about it later to see how it turned out."}


@tool
def record_choice(decision_id: int, chose: str) -> dict:
    """Record what was actually decided, once it is decided."""
    _get_store().record_choice(_decision(decision_id), chose)
    return {"decision_id": decision_id, "chose": chose}


@tool
def record_outcome(decision_id: int, outcome: str, rating: int) -> dict:
    """Record how a past decision actually turned out.

    Rating runs -2 (went badly) to +2 (went well). This is what makes the
    journal worth keeping: it is the only way to find out whether the advice
    was any good.
    """
    _get_store().record_outcome(_decision(decision_id), outcome, rating)
    return {"decision_id": decision_id, "outcome": outcome, "rating": rating}


@tool
def add_life_event(happened_on: str, title: str, category: str | None = None,
                   precision: str = "day", significance: int = 3,
                   person_id: int | str | None = None) -> dict:
    """Record something dated that happened.

    Useful immediately as context, and later as the evidence a birth-time
    rectification is tested against.
    """
    pid = _resolve(person_id)
    event_id = _get_store().add_life_event(
        pid, happened_on, title, precision=precision, category=category,
        significance=significance)
    return {"event_id": event_id, "happened_on": happened_on, "title": title}


# ------------------------------------------------------ day scale and weight


@tool
def panchanga_for(date: str, person_id: int | str | None = None) -> dict:
    """The five limbs of a day: tithi, weekday, nakshatra, yoga and karana,
    each with the time it ends, plus sunrise, sunset and Rahu Kaal.

    This is the day-scale layer. Use it for "is today right for the
    conversation" or "when this week should I sign" -- questions where the Moon
    and the weekday matter and the dashas do not move at all. Do not reach for
    it on a career or relocation question; nothing here changes those.

    Computed for the birthplace unless the person says where they are now.
    """
    from . import panchanga
    pid = _resolve(person_id)
    row = _get_store().active_chart_row(pid)
    return panchanga.panchanga(tools._jd(date), row["latitude"],
                               row["longitude"], row["ayanamsa"])


@tool
def graha_strength(person_id: int | str | None = None) -> list[dict]:
    """How strong each graha is in the natal chart, and why.

    Use this to weigh conflicting factors rather than averaging them. An
    exalted, well-placed graha aspecting a house means something a combust or
    debilitated one does not, and that difference is usually what decides a
    close call.
    """
    from . import strength
    pid = _resolve(person_id)
    chart = _get_store().compute(_get_store().active_chart_row(pid))
    return [s.as_dict() for s in strength.assess(chart)]


@tool
def transit_support(body: str, date: str, person_id: int | str | None = None) -> dict:
    """Whether a transit is well supported FOR THIS CHART, by ashtakavarga.

    This is the classical answer to why two people meet the same transit
    differently. Five or more of a graha's own bindus in the sign it is
    crossing favours it; two or fewer works against it. Consult this before
    calling any transit good or bad -- a generic reading will be wrong for
    roughly half of charts.
    """
    from . import strength, transits
    pid = _resolve(person_id)
    store = _get_store()
    row = store.active_chart_row(pid)
    chart = store.compute(row)
    if body not in strength.ASHTAKAVARGA:
        return {"error": f"ashtakavarga covers the seven grahas: "
                         f"{sorted(strength.ASHTAKAVARGA)}. The nodes have no "
                         f"table of their own."}
    longitude, _speed = transits.state(tools._jd(date), body, row["ayanamsa"])
    return {**strength.transit_support(chart, body, int(longitude // 30)),
            "date": date}


@tool
def test_birth_time(candidates: list[str],
                    person_id: int | str | None = None) -> dict:
    """Test candidate birth times on WHICH lords were running at real events.

    A stronger test than propose_rectification's timing check. That one asks
    whether events fell near a dasha boundary, which is cheap to satisfy by
    luck. This asks whether the RIGHT lord was running: the Sun or the 9th
    lord when a father died, Venus or the 7th when someone married, Saturn or
    the 10th at a career turn.

    Report the lift above chance, not the raw score. Several lords qualify for
    most rules and two run at any moment, so a wrong chart still matches most
    events -- the score alone flatters every candidate.

    Give times as "HH:MM". Use it when a birth time is disputed, and be willing
    to report that it settles nothing, which is common.
    """
    from . import dasha, ephemeris, karaka, timeplace
    pid = _resolve(person_id)
    store = _get_store()
    row = store.active_chart_row(pid)
    events = [dict(e) for e in store.life_events(pid)]
    y, mo, d = (int(x) for x in row["birth_date"].split("-"))

    out = []
    for text in candidates:
        try:
            parts = [int(x) for x in text.split(":")]
            hh, mm = parts[0], parts[1]
        except (ValueError, IndexError):
            return {"error": f"could not read {text!r}; use HH:MM"}
        m = timeplace.resolve(y, mo, d, hh, mm, row["latitude"],
                              row["longitude"])
        chart = ephemeris.compute_chart(m.julian_day_ut, row["latitude"],
                                        row["longitude"], row["ayanamsa"])
        tree = dasha.compute(chart.get("Moon").longitude, m.julian_day_ut,
                             levels=2)
        r = karaka.fit(chart, tree, events)
        base = karaka.baseline(chart, events)
        out.append({
            "birth_time": f"{hh:02d}:{mm:02d}",
            "lagna": chart.ascendant.sign_english,
            "matched": f"{r['matched']} of {r['events_testable']}",
            "score": r["score"], "chance_level": base,
            "lift_above_chance": round(r["score"] - base, 3),
            "misses": [f"{d.happened_on} {d.event} (expected "
                       f"{'/'.join(d.expected)}, ran {'/'.join(d.running)})"
                       for d in r["detail"] if not d.matched][:5],
        })
    out.sort(key=lambda x: x["lift_above_chance"], reverse=True)
    return {"candidates": out,
            "note": "Lift above chance is the figure that matters. A gap of "
                    "less than about 0.15 between candidates does not settle "
                    "anything, and this test disagreeing with the timing test "
                    "means neither is strong enough to overrule testimony or "
                    "a birth record."}


# --------------------------------------------------- structure and refining


@tool
def yogas_in_chart(person_id: int | str | None = None) -> list[dict]:
    """The classical combinations this chart carries, with what each rests on.

    Call this when the question is about the shape of someone's life rather
    than a moment in it -- what they are built for, where the strengths and the
    recurring difficulties sit. Findings that depend on a disputed definition
    carry a caveat; quote it rather than dropping it.
    """
    from . import yogas
    store = _get_store()
    chart = store.compute(store.active_chart_row(_resolve(person_id)))
    return [y.as_dict() for y in yogas.detect(chart)]


@tool
def aspects_on_house(house: int, person_id: int | str | None = None) -> dict:
    """Which grahas aspect a given house, and which occupy it.

    Every graha aspects the seventh from itself; Mars also the fourth and
    eighth, Jupiter the fifth and ninth, Saturn the third and tenth.
    """
    from . import yogas
    if not 1 <= house <= 12:
        return {"error": "house must be between 1 and 12"}
    store = _get_store()
    chart = store.compute(store.active_chart_row(_resolve(person_id)))
    return {
        "house": house,
        "sign": ephemeris_sign(chart, house),
        "lord": yogas.house_lord(chart, house),
        "occupied_by": [p.name for p in chart.positions if p.house == house],
        "aspected_by": [p.name for p in chart.positions
                        if yogas.aspects_house(chart, p.name, house)],
    }


def ephemeris_sign(chart, house: int) -> str:
    from . import ephemeris
    return ephemeris.SIGNS[chart.sign_in_house(house)][1]


@tool
def propose_rectification(person_id: int | str | None = None,
                          step_minutes: float = 2.0) -> dict:
    """Narrow an uncertain birth time against the dated life events on record.

    Nothing is written. This returns candidates for a person to judge, and it
    will say plainly when the events do not distinguish between them -- which
    is common and is the honest answer, not a failure. Do not adopt a candidate
    on its own; put it to them, with what it rests on.
    """
    from . import rectify
    pid = _resolve(person_id)
    return rectify.rectify(_get_store(), pid, step_minutes=step_minutes).as_dict()


@tool
def apply_rectification(birth_time: str, note: str,
                        person_id: int | str | None = None) -> dict:
    """Store a rectified birth time as a NEW chart version.

    Only call this once the person has explicitly accepted a candidate. The
    original is kept and stays comparable; `note` should record why this time
    was chosen, because a future reader will need it.

    The stored confidence is NOT fixed: it is derived from how tightly the
    plausible candidates clustered. A rectification that narrowed a three-hour
    window to five minutes is stored as such, and one that narrowed it to an
    hour is stored as an hour. Claiming more would license divisional charts
    and precise dates that the evidence never supported.

    birth_time is local clock time, HH:MM or HH:MM:SS.
    """
    from .confidence import TimeConfidence
    pid = _resolve(person_id)
    store = _get_store()
    row = store.active_chart_row(pid)
    y, mo, d = (int(x) for x in row["birth_date"].split("-"))
    try:
        parts = [int(x) for x in birth_time.split(":")]
        hh, mm = parts[0], parts[1]
        ss = parts[2] if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return {"error": "birth_time must be HH:MM or HH:MM:SS"}

    # Derive the confidence from the evidence rather than assuming the
    # rectification hit the exact minute.
    from . import rectify
    proposal = rectify.rectify(store, pid, step_minutes=2.0)
    level = TimeConfidence[proposal.implied_confidence]
    detail = (f"{note} [Supported spread +/-{proposal.spread_minutes:.0f} min, "
              f"so stored as {level.name}.]")

    chart_id = store.add_chart(
        pid, y, mo, d, hh, mm, ss, row["place_name"], row["latitude"],
        row["longitude"], level, row["ayanamsa"],
        derived_from_id=row["id"], rectification_note=detail)
    _runners.pop((store.account_id, pid), None)
    new_row = store.active_chart_row(pid)
    chart = store.compute(new_row)
    rel = store.reliability(new_row)
    return {
        "chart_id": chart_id,
        "birth_time": f"{hh:02d}:{mm:02d}:{ss:02d}",
        "lagna": f"{chart.ascendant.sign_english}",
        "previous_version_kept": row["id"],
        "now_permits": {k: rel.allows(k) for k in
                        ("house_placement", "dasha_date", "navamsa",
                         "shashtiamsa")},
        "dates_may_be_stated": rel.date_precision,
        "stored_confidence": level.name,
        "supported_spread_minutes": round(proposal.spread_minutes, 1),
        "plausible_lagnas": proposal.plausible_lagnas,
        "note": (f"Stored as {level.name}, derived from how tightly the "
                 f"candidates clustered rather than assumed. A rectified time "
                 f"is an inference, not a record."
                 + ("  WARNING: the plausible candidates disagree on the "
                    "ascendant, so which chart this person has is still open."
                    if len(proposal.plausible_lagnas) > 1 else "")),
    }


# ------------------------------------------------------- is today good for me


@tool
def personal_day(date: str | None = None, days: int = 1,
                 favourable_only: bool = False,
                 person_id: int | str | None = None) -> dict:
    """Tara bala and Chandra bala: whether a day suits THIS person.

    The panchanga is identical for everyone standing in the same place. These
    two are counted from the natal Moon, so two people meet the same tithi and
    nakshatra on opposite terms. Whenever you are about to call a day good or
    bad for someone, check here -- panchanga_for alone describes the sky, not
    the person.

    Set `days` above 1 to scan forward, and favourable_only to pick out the
    days both measures agree on. The Tara changes when the Moon changes
    nakshatra, which is roughly daily but not at midnight, so a calendar day
    can carry two; `changes_at` says when.

    Treat it as qualifying an answer, never as the answer. A good Tara does not
    make a decision right.
    """
    from datetime import date as date_cls
    from . import personalday
    pid = _resolve(person_id)
    store = _get_store()
    chart = store.compute(store.active_chart_row(pid))
    when = date or date_cls.today().isoformat()
    y, mo, d = (int(x) for x in when.split("-"))
    jd = __import__("swisseph").julday(y, mo, d, 6.0)

    if days <= 1 and not favourable_only:
        return {"date": when, **personalday.at(chart, jd).as_dict()}
    if favourable_only:
        picked = personalday.best_days(chart, jd, max(days, 30))
        return {"from": when, "days_scanned": max(days, 30),
                "favourable_days": picked,
                "note": "Days where the Tara and the Moon's placement from "
                        "your natal Moon both agree. Absence of a day here is "
                        "not a prohibition."}
    return {"from": when, "days": personalday.window(chart, jd, days)}


# ------------------------------------------------------- saturn from the moon


@tool
def saturn_from_moon(date: str | None = None,
                     person_id: int | str | None = None) -> dict:
    """Sade Sati and its smaller relatives, measured from the natal Moon.

    Every other tool here counts houses from the ascendant. This one does not,
    and that is the point: Sade Sati is Saturn crossing the 12th, 1st and 2nd
    from the MOON. A chart can have Saturn somewhere unremarkable from the
    lagna and still be in the middle of its hardest Saturn period, so checking
    transits_at alone will miss it.

    Call this whenever someone asks why a stretch of years has been heavy, or
    about Sade Sati by name -- it is the thing people ask about most and most
    often have half-right. The answer includes when it started, when it ends,
    which phase is running, and how far through it is.

    Also reports Kantaka Shani (Saturn in the 4th from the Moon) and Ashtama
    Shani (the 8th), which are shorter and milder but real.
    """
    from datetime import date as date_cls
    from . import shani
    pid = _resolve(person_id)
    store = _get_store()
    row = store.active_chart_row(pid)
    chart = store.compute(row)
    when = date or date_cls.today().isoformat()
    y, mo, d = (int(x) for x in when.split("-"))
    return {"date": when,
            **shani.status(chart, __import__("swisseph").julday(y, mo, d, 12.0))}


# ---------------------------------------------------- weight and exact timing


@tool
def graha_shadbala(person_id: int | str | None = None) -> dict:
    """Numeric strength, so grahas can be RANKED rather than just described.

    graha_strength says a graha is exalted or combust. This puts numbers on it,
    which is what you need when two factors point opposite ways and one has to
    win. Reach for it when you are about to say "on balance" -- that is the
    moment the numbers are worth having.

    Partial: five well-defined components of the six-fold Shadbala, with the
    rest named in the response. The totals compare grahas WITHIN this chart and
    must not be measured against the classical minimum strengths.
    """
    from . import shadbala
    pid = _resolve(person_id)
    store = _get_store()
    row = store.active_chart_row(pid)
    hh, mm, _ss = (int(x) for x in row["birth_time"].split(":"))
    return shadbala.assess(store.compute(row), birth_hour=hh + mm / 60)


@tool
def transit_contacts(start: str, end: str, bodies: list[str] | None = None,
                     natal_points: list[str] | None = None,
                     person_id: int | str | None = None) -> dict:
    """Dated moments when a transiting graha reaches a natal point exactly.

    "Saturn is in your 10th" holds for two and a half years and cannot time
    anything. "Saturn's aspect falls exactly on your natal Moon on 14 June" is
    a date. Use this to put specific days into a timing answer, after
    events_between has given you the broader shape.

    Counts conjunctions and the graha's own aspects -- Mars the 4th and 8th,
    Jupiter the 5th and 9th, Saturn the 3rd and 10th. Where a contact repeats,
    the graha crossed it, turned retrograde back over it, and crossed again:
    three separate occasions, and worth saying so.

    Narrow with `bodies` and `natal_points` when a question is about one thing;
    the unfiltered list over two years runs to dozens.
    """
    from . import contacts
    pid = _resolve(person_id)
    store = _get_store()
    chart = store.compute(store.active_chart_row(pid))
    kwargs = {}
    if bodies:
        kwargs["transiting"] = tuple(bodies)
    if natal_points:
        kwargs["natal_points"] = tuple(natal_points)
    return contacts.summary(chart, tools._jd(start), tools._jd(end), **kwargs)


# ------------------------------------------------------------------ drawing


@tool
def chart_image(kind: str = "natal", date: str | None = None,
                highlight: list[int] | None = None,
                person_id: int | str | None = None) -> str:
    """An SVG of the chart, to show alongside an answer.

    kind is "natal" for the birth chart alone, or "transit" to lay the grahas
    of a given date into the natal houses -- which is what gochara means in
    practice: not where the sky is, but where it is relative to this person.

    `highlight` tints the houses the question turns on, so the drawing points
    at something rather than just existing.

    Put the result in an artifact. It is support for the answer, never the
    answer itself -- do not walk through the chart because you drew it.
    """
    from datetime import date as date_cls
    from . import chartsvg
    pid = _resolve(person_id)
    store = _get_store()
    row = store.active_chart_row(pid)
    chart = store.compute(row)
    person = store.person(pid)

    if kind not in ("natal", "transit"):
        raise ToolError('kind must be "natal" or "transit"')
    when = date or date_cls.today().isoformat()
    caption = (f"{person['name']} -- natal" if kind == "natal"
               else f"{person['name']} -- transits for {when}")
    return chartsvg.north_indian(
        chart, transit_date=None if kind == "natal" else when,
        caption=caption, highlight=highlight)


# ---------------------------------------------------------------- onboarding


@tool
def search_places(query: str, limit: int = 8) -> list[dict]:
    """Find a birthplace by city name, from the advisor's own database.

    No outside service is asked. If the birthplace is a village the database
    does not know, ask for coordinates instead and use parse_coordinates.
    """
    from . import timeplace
    return [{"name": p.name, "country": p.country, "latitude": p.latitude,
             "longitude": p.longitude, "population": p.population}
            for p in timeplace.search_places(query, limit)]


@tool
def parse_coordinates(text: str) -> dict:
    """Read coordinates in whatever format they were pasted.

    Accepts decimal pairs, degrees-minutes-seconds, hemisphere letters leading
    or trailing. Tell the person they can right-click the spot in Google Maps
    and paste whatever it gives them.
    """
    from . import coords, timeplace
    try:
        c = coords.parse(text)
    except coords.CoordinateError as exc:
        return {"error": str(exc)}
    return {"latitude": c.latitude, "longitude": c.longitude,
            "formatted": str(c),
            "timezone": timeplace.timezone_for(c.latitude, c.longitude)}


@tool
def create_profile(name: str, birth_date: str, birth_time: str,
                   place_name: str, latitude: float, longitude: float,
                   time_confidence: str, relation: str = "self",
                   ayanamsa: str = "LAHIRI") -> dict:
    """Create a profile and compute its chart.

    birth_date is YYYY-MM-DD and birth_time is HH:MM or HH:MM:SS, both as the
    LOCAL clock read at the birthplace -- historical timezone rules are applied
    here, so do not convert anything yourself.

    time_confidence is one of EXACT, RECTIFIED, REMEMBERED, TO_THE_HOUR, VAGUE.
    Ask for it rather than assuming: it decides what may later be claimed, and
    a wrong answer here quietly licenses advice the birth time cannot support.

    Read the response. An ambiguous or nonexistent local time needs a human
    answer, not a guess.
    """
    from .confidence import TimeConfidence
    from . import ephemeris

    try:
        conf = TimeConfidence[time_confidence.upper()]
    except KeyError:
        return {"error": f"time_confidence must be one of "
                         f"{[c.name for c in TimeConfidence]}"}
    if ayanamsa not in ephemeris.AYANAMSAS:
        return {"error": f"ayanamsa must be one of {sorted(ephemeris.AYANAMSAS)}"}
    try:
        y, mo, d = (int(x) for x in birth_date.split("-"))
        parts = [int(x) for x in birth_time.split(":")]
        hh, mm = parts[0], parts[1]
        ss = parts[2] if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return {"error": "birth_date must be YYYY-MM-DD and birth_time HH:MM"}

    store = _get_store()
    pid = store.add_person(name, relation)
    store.add_chart(pid, y, mo, d, hh, mm, ss, place_name,
                    latitude, longitude, conf, ayanamsa)
    _runners.pop((store.account_id, pid), None)
    row = store.active_chart_row(pid)
    chart = store.compute(row)

    warnings = []
    if row["time_nonexistent"]:
        warnings.append("That local time never occurred -- the clocks went "
                        "forward through it. The recorded time needs checking.")
    if row["time_ambiguous"]:
        warnings.append("That local time occurred twice that day, when the "
                        "clocks went back. Which one is meant changes the chart.")
    if row["used_local_mean_time"]:
        warnings.append(
            f"This birth predates standard time in that region, so the "
            f"birthplace's own mean time was used "
            f"({row['utc_offset_hours']:+.4f}h rather than "
            f"{row['iana_offset_hours']:+.4f}h).")

    return {"person_id": pid,
            "lagna": f"{ephemeris.dms(chart.ascendant.degrees_in_sign)} "
                     f"{chart.ascendant.sign} ({chart.ascendant.sign_english})",
            "timezone": row["timezone_name"],
            "utc_offset_hours": row["utc_offset_hours"],
            "warnings": warnings,
            "next": "Ask for five to ten dated life events and record each with "
                    "add_life_event. They give you a history to reason from, and "
                    "they are what any later birth-time rectification is tested "
                    "against."}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
