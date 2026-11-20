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

import sqlite3

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

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

Both are worked out for where the person is on the date asked about, not
where they were born. chart_context says what is on record: "NOW IN" is where
they live, "AWAY" is a dated stay elsewhere. If neither is recorded, ask where
they live before the first day-scale answer and save it with
set_current_place; a reply that carries place_warning was computed for the
birthplace and is wrong for anyone living elsewhere. When they mention a trip,
ask the dates and record it as a stay with `until`, never by overwriting where
they live: a stay ends by itself. Say which place an answer was computed for.

NUMBERS YOU DID NOT COMPUTE

Every clock time a tool returns is already in the local time of the place it
names, with the offset shown. Quote it exactly. Never convert a time between
zones yourself, never add or subtract hours, never work out a weekday or a
count of days in your head. If a time is wanted for another place, call the
tool again with that place. If a count is wanted, use the count the tool
states (chart_context states how many life events are on record; a list of
favourable days states how many it holds). If no tool gives the number, say
you do not have it rather than estimate.

Never say you checked, recounted, verified or computed something unless a
tool call in this conversation did it. If you worked something out by reading
or by reasoning, say so in those words.

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

If a profile holds a mistake -- a misspelt name, the wrong birth date, time or
place -- call correct_profile. Birth data is never overwritten: the correction
becomes a new chart version and the old one is kept. To delete a profile, call
remove_profile once to see what would go, tell the person exactly that, and
call it again with confirm_name only after they have said yes in so many
words. If a back_up_data tool is offered, use it when they ask for a backup,
and suggest it after a session that added a lot.
"""

mcp = MCPServer(
    name="zeljko",
    title="Zeljko, the jyotisha advisor",
    instructions=INSTRUCTIONS,
)

# Every tool, in order, so the shared server (backend/remote.py) can offer the
# same set over HTTP without a second list to keep in step.
TOOLS: list = []

# The tools that change what is stored. Every other tool only looks things up
# or computes, and is declared read-only, so Claude Desktop can let a person
# approve all of those together instead of one prompt per tool. A new tool
# that writes must be named here, or it is offered as harmless when it is
# not. verify_extension.py checks every tool carries one mark or the other.
WRITES = {"create_profile", "correct_profile", "remove_profile",
          "set_current_place",
          "add_life_event", "record_decision", "record_choice",
          "record_outcome", "apply_rectification", "back_up_data"}
# Of those, the ones that can take something away.
DESTRUCTIVE = {"remove_profile"}


def marks(name: str) -> ToolAnnotations:
    """What a tool declares about itself. Nothing here reaches outside the
    person's own computer, so none is open-world."""
    if name not in WRITES:
        return ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    return ToolAnnotations(readOnlyHint=False, openWorldHint=False,
                           destructiveHint=name in DESTRUCTIVE)


def register(server, fn):
    """Offer one tool on a server, with its marks. The only way a tool is
    registered, here and in remote.py, extension.py and guidance.py."""
    return server.tool(annotations=marks(fn.__name__))(fn)


def tool(fn):
    TOOLS.append(fn)
    return register(mcp, fn)


# Tools that only make sense where the database is the person's own file on
# their own computer. The shared server does not offer these.
LOCAL_TOOLS: list = []


def local_tool(fn):
    LOCAL_TOOLS.append(fn)
    return register(mcp, fn)


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
        try:
            _store = Store()
        except (OSError, sqlite3.Error) as exc:
            from .store import DB_PATH
            raise ToolError(
                f"The database could not be opened at {DB_PATH} ({exc}). "
                f"Tell the person: check that this folder exists and can be "
                f"written to, or choose another data folder in the "
                f"extension's settings, then restart Claude.") from None
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


def _where(pid: int, place: str | None = None,
           on: str | None = None) -> dict:
    """The place a day-scale answer is worked out for, and how it was chosen:
    the one named in the call, else a stay covering that date, else where the
    person lives, else the birthplace."""
    from . import timeplace
    store = _get_store()
    if place and place.strip():
        try:
            return {**timeplace.locate(place), "chosen": "named in this call"}
        except ValueError as exc:
            return {"error": str(exc)}
    saved = store.current_place(pid, on=on)
    if saved and "until" in saved:
        return {**saved, "other_matches": [],
                "chosen": f"a stay on record, {saved['from']} until "
                          f"{saved['until']}"}
    if saved:
        return {**saved, "other_matches": [],
                "chosen": "saved as where this person lives"}
    row = store.active_chart_row(pid)
    return {"name": row["place_name"], "latitude": row["latitude"],
            "longitude": row["longitude"],
            "timezone": timeplace.timezone_for(row["latitude"],
                                               row["longitude"]),
            "other_matches": [], "chosen": "birthplace"}


def _today(pid: int, place: str | None) -> str:
    """Today's date where the person is, not where this program runs."""
    from datetime import datetime, timezone
    from . import timeplace
    now = datetime.now(timezone.utc)
    where = _where(pid, place, on=now.date().isoformat())
    if "error" in where:
        return now.date().isoformat()
    return timeplace.local(now, where["timezone"]).date().isoformat()


def _where_note(where: dict) -> dict:
    out = {"computed_for": where["name"],
           "times_are": f"local clock time in {where['name']} "
                        f"({where['timezone']}), already converted. Quote "
                        "them as given; do not convert them."}
    if where["chosen"] == "birthplace":
        out["place_warning"] = (
            "No current place is recorded, so this is for the BIRTHPLACE. If "
            "the person is somewhere else now, ask where, save it with "
            "set_current_place, and call this again. Sunrise, the day's "
            "limbs and every time here depend on it.")
    else:
        out["place_chosen"] = where["chosen"]
    if where.get("other_matches"):
        out["other_places_with_that_name"] = where["other_matches"]
    return out


@tool
def set_current_place(place: str, person_id: int | str | None = None,
                      until: str | None = None,
                      starting: str | None = None) -> dict:
    """Record where a person is, when it is not where they were born.

    Day-scale answers depend on it: sunrise, the limbs of the day, Rahu Kaal
    and the hour a favourable stretch begins are different in another city,
    and are given in that city's clock time. panchanga_for and personal_day
    then use it without being told.

    Two kinds, and which one you record matters:

    - Where they LIVE: call with the place only. Ask once ("where are you
      living now?"). It stays until changed.
    - A STAY somewhere else -- a trip, a month abroad: also pass `until`, the
      last day there (YYYY-MM-DD), and `starting`, the first day, if it has
      not begun yet (it defaults to today). The home place is left alone. The
      stay is used for dates inside it and lapses by itself afterwards, so
      always prefer this for travel, and ask for the return date rather than
      overwrite where they live. A question about a date after the stay is
      answered for home.

    `place` is a city ("Lisbon"), a city and country ("Springfield, US"), or
    coordinates pasted from a map. An empty string ends a stay if one is on
    record ("I came back early"); with no stay on record it clears where they
    live and day-scale answers go back to the birthplace. Read the reply: if
    `other_places_with_that_name` is not empty, confirm with the person which
    one they meant.

    This changes nothing about the birth chart. For a single question about
    one day somewhere else, do not record anything: pass `place` to
    panchanga_for or personal_day.
    """
    from datetime import date as date_cls
    from . import timeplace
    pid = _resolve(person_id)
    store = _get_store()
    name = store.person(pid)["name"]
    if not place.strip():
        if store.stay(pid):
            store.set_stay(pid, None)
            home = store.current_place(pid)
            return {"person": name, "stay": None,
                    "note": "The stay is ended. Day-scale answers use "
                            + (home["name"] if home else "the birthplace")
                            + " again."}
        store.set_current_place(pid, None)
        return {"person": name, "lives_in": None,
                "note": "Cleared. Day-scale answers use the birthplace again."}
    try:
        found = timeplace.locate(place)
    except ValueError as exc:
        return {"error": str(exc)}
    seen = {"timezone": found["timezone"], "latitude": found["latitude"],
            "longitude": found["longitude"],
            "other_places_with_that_name": found["other_matches"]}
    if until is None and starting is None:
        store.set_current_place(pid, found["name"], found["latitude"],
                                found["longitude"], found["timezone"])
        return {"person": name, "lives_in": found["name"], **seen}
    if until is None:
        return {"error": "A stay needs its last day: pass `until` as "
                         "YYYY-MM-DD. Ask the person when they come back."}
    try:
        last = date_cls.fromisoformat(until[:10]).isoformat()
        first = (date_cls.fromisoformat(starting[:10]).isoformat()
                 if starting else _today(pid, found["name"]))
        store.set_stay(pid, found["name"], found["latitude"],
                       found["longitude"], found["timezone"], first, last)
    except ValueError as exc:
        return {"error": f"{exc}. Dates are YYYY-MM-DD."}
    home = store.current_place(pid)
    return {"person": name, "stay": found["name"], "from": first,
            "until": last, **seen,
            "afterwards": (home["name"] if home else "the birthplace")
                          + " is used again from the day after, by itself."}


@tool
def panchanga_for(date: str, person_id: int | str | None = None,
                  place: str | None = None) -> dict:
    """The five limbs of a day: tithi, weekday, nakshatra, yoga and karana,
    each with the time it ends, plus sunrise, sunset and Rahu Kaal.

    This is the day-scale layer. Use it for "is today right for the
    conversation" or "when this week should I sign" -- questions where the Moon
    and the weekday matter and the dashas do not move at all. Do not reach for
    it on a career or relocation question; nothing here changes those.

    `date` is a calendar date where the person is. The answer is for the day
    that opens at sunrise on that date, there.

    Computed for where the person is on that date: `place` if you pass one (a
    city, or "City, Country", or coordinates), else a stay recorded with
    set_current_place that covers the date, else where they live, else the
    birthplace. The answer says which was used.
    Every time in it is already the clock time of that place. Quote them as
    given and never convert a time yourself; if another place's time is
    wanted, call again with that place.
    """
    from . import panchanga, timeplace
    pid = _resolve(person_id)
    where = _where(pid, place, on=date)
    if "error" in where:
        return where
    row = _get_store().active_chart_row(pid)
    # Noon on that date, there: the sunrise before it is that day's sunrise.
    jd = timeplace.julian_day(timeplace.instant(date, 12.0, where["timezone"]))
    return {"date": date[:10], **_where_note(where),
            **panchanga.panchanga(jd, where["latitude"], where["longitude"],
                                  row["ayanamsa"], where["timezone"])}


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
                 person_id: int | str | None = None,
                 place: str | None = None) -> dict:
    """Tara bala and Chandra bala: whether a day suits THIS person.

    Dates are calendar dates where the person is now (see panchanga_for for
    how that place is chosen), each judged at nine in the morning there. The
    time a Tara changes is that place's clock time, already converted: quote
    it as given and never convert a time yourself.

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
    when = date[:10] if date else _today(pid, place)
    first = _where(pid, place, on=when)
    if "error" in first:
        return first

    # Someone travelling is in one place on Monday and another on Thursday:
    # each date is judged for where they are on that date.
    spots: dict[str, dict] = {}

    def zone_on(day: str) -> str:
        spots[day] = _where(pid, place, on=day)
        return spots[day]["timezone"]

    def scan(count: int) -> tuple[list[dict], dict]:
        rows = personalday.local_days(chart, when, count, zone_on)
        note = _where_note(first)
        if len({w["name"] for w in spots.values()}) > 1:
            for r in rows:
                r["place"] = spots[r["date"]]["name"]
            note["computed_for"] = ("more than one place: a stay begins or "
                                    "ends inside these dates. Each day names "
                                    "its own place.")
            note["times_are"] = ("local clock time in the place named on "
                                 "each day, already converted. Quote them as "
                                 "given; do not convert them.")
        return rows, note

    if days <= 1 and not favourable_only:
        rows, note = scan(1)
        return {**note, **rows[0]}
    if favourable_only:
        scanned = max(days, 30)
        rows, note = scan(scanned)
        picked = [d for d in rows if d["verdict"] == "favourable"]
        return {"from": when, "days_scanned": scanned, **note,
                "favourable_count": len(picked),
                "favourable_days": picked,
                "note": "Days where the Tara and the Moon's placement from "
                        "your natal Moon both agree. Absence of a day here is "
                        "not a prohibition."}
    rows, note = scan(days)
    return {"from": when, **note, "days": rows}


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

    return {"person_id": pid,
            "lagna": _lagna(store, row),
            "timezone": row["timezone_name"],
            "utc_offset_hours": row["utc_offset_hours"],
            "warnings": _time_warnings(row),
            "next": "Ask for five to ten dated life events and record each with "
                    "add_life_event. They give you a history to reason from, and "
                    "they are what any later birth-time rectification is tested "
                    "against."}


def _lagna(store: Store, row: dict) -> str:
    from . import ephemeris
    chart = store.compute(row)
    return (f"{ephemeris.dms(chart.ascendant.degrees_in_sign)} "
            f"{chart.ascendant.sign} ({chart.ascendant.sign_english})")


def _time_warnings(row: dict) -> list[str]:
    """What a human has to settle about a stored local birth time."""
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
    return warnings


# ------------------------------------------------------ fixing and removing


@tool
def correct_profile(note: str, name: str | None = None,
                    relation: str | None = None,
                    birth_date: str | None = None,
                    birth_time: str | None = None,
                    place_name: str | None = None,
                    latitude: float | None = None,
                    longitude: float | None = None,
                    time_confidence: str | None = None,
                    person_id: int | str | None = None) -> dict:
    """Fix a mistake in a profile: the name, the relation, or the birth data.

    Pass only what is changing. `note` says what was wrong and how the right
    value is known ("typo in the year; checked against the birth
    certificate"), because a later reader will need it.

    Nothing about a birth is overwritten. A changed date, time, place or
    time_confidence is stored as a NEW chart version that becomes the active
    one; the earlier version is kept, and journal entries made under it still
    point at it. A changed place needs its coordinates too -- get them from
    search_places or parse_coordinates, never from memory.

    birth_date is YYYY-MM-DD and birth_time HH:MM or HH:MM:SS, as the local
    clock read at the birthplace. Read the warnings in the response, as after
    create_profile. This is for correcting a record that was entered wrong;
    narrowing an uncertain time against life events is apply_rectification.
    """
    from .confidence import TimeConfidence
    pid = _resolve(person_id)
    store = _get_store()
    row = store.active_chart_row(pid)

    if not note.strip():
        return {"error": "note is required: say what was wrong and how the "
                         "right value is known"}
    if (latitude is None) != (longitude is None):
        return {"error": "give latitude and longitude together"}
    if place_name is not None and latitude is None \
            and place_name.strip() != row["place_name"]:
        return {"error": "a changed place needs its coordinates: look it up "
                         "with search_places or parse_coordinates"}
    birth_changes = (birth_date, birth_time, place_name, latitude,
                     time_confidence)
    if name is None and relation is None and not any(
            v is not None for v in birth_changes):
        return {"error": "nothing to change was given"}
    if name is not None and not name.strip():
        return {"error": "name must not be empty"}

    try:
        conf = TimeConfidence[(time_confidence or row["time_confidence"]).upper()]
    except KeyError:
        return {"error": f"time_confidence must be one of "
                         f"{[c.name for c in TimeConfidence]}"}
    try:
        y, mo, d = (int(x) for x in (birth_date or row["birth_date"]).split("-"))
        parts = [int(x) for x in (birth_time or row["birth_time"]).split(":")]
        hh, mm = parts[0], parts[1]
        ss = parts[2] if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return {"error": "birth_date must be YYYY-MM-DD and birth_time HH:MM"}

    copy = store.safety_copy("correct-profile")
    changed = [k for k, v in (("name", name), ("relation", relation))
               if v is not None]
    out: dict = {"person_id": pid}
    if any(v is not None for v in birth_changes):
        try:
            chart_id = store.add_chart(
                pid, y, mo, d, hh, mm, ss, place_name or row["place_name"],
                row["latitude"] if latitude is None else latitude,
                row["longitude"] if longitude is None else longitude,
                conf, row["ayanamsa"], derived_from_id=row["id"],
                rectification_note=f"Correction: {note.strip()}")
        except ValueError as exc:
            return {"error": f"that birth data could not be used: {exc}"}
        _runners.pop((store.account_id, pid), None)
        new_row = store.active_chart_row(pid)
        rel = store.reliability(new_row)
        changed += [k for k, v in (
            ("birth_date", birth_date), ("birth_time", birth_time),
            ("place", place_name if place_name is not None else latitude),
            ("time_confidence", time_confidence)) if v is not None]
        out.update({
            "chart_id": chart_id,
            "previous_version_kept": row["id"],
            "birth": f"{new_row['birth_date']} {new_row['birth_time']} local, "
                     f"{new_row['place_name']}",
            "lagna": _lagna(store, new_row),
            "lagna_before": _lagna(store, row),
            "timezone": new_row["timezone_name"],
            "time_confidence": new_row["time_confidence"],
            "dates_may_be_stated": rel.date_precision,
            "warnings": _time_warnings(new_row),
            "note": "Stored as a new chart version; the earlier one is kept. "
                    "If the lagna changed, say so plainly: earlier answers "
                    "were read from a different chart and may not hold."})
    # Last, so a birth correction that is refused leaves the name alone too.
    if name is not None or relation is not None:
        store.update_person(pid, name=name, relation=relation)
    out["changed"] = changed
    if copy is not None:
        out["safety_copy"] = str(copy)
    return out


@tool
def remove_profile(person_id: int | str, confirm_name: str = "") -> dict:
    """Delete a profile and everything stored under it. Two steps, always.

    First call it WITHOUT confirm_name. Nothing is deleted: it returns the
    profile's name and what would go with it -- every chart version, every
    life event, every journal entry. Tell the person exactly that and ask
    whether they are sure.

    Only after they have clearly said yes, call it again with confirm_name
    set to the profile's name as returned. Never fill confirm_name in on your
    own initiative, and never to tidy up: a mistake in a profile is fixed
    with correct_profile, not by deleting and starting again, because
    deleting takes the journal with it.

    Name the profile explicitly; this tool never assumes whose it is.
    """
    pid = _resolve(person_id)
    store = _get_store()
    name = store.person(pid)["name"]
    holds = store.holdings(pid)
    if not confirm_name.strip():
        return {"deleted": False, "name": name, "would_delete": holds,
                "next": "Nothing was deleted. Tell the person what would be "
                        "removed and ask if they are sure. If they say yes, "
                        "call remove_profile again with confirm_name set to "
                        f"{name!r}."}
    if confirm_name.strip().lower() != name.strip().lower():
        return {"deleted": False,
                "error": "confirm_name does not match this profile's name. "
                         "Nothing was deleted."}
    copy = store.safety_copy("remove-profile")
    store.delete_person(pid)
    _runners.pop((store.account_id, pid), None)
    out = {"deleted": True, "name": name, "removed": holds}
    if copy is not None:
        out["safety_copy"] = str(copy)
        out["note"] = ("A copy of the whole database from just before the "
                       "removal was kept at the path above, in case this was "
                       "a mistake.")
    else:
        out["note"] = "This is permanent. No copy was kept."
    return out


@local_tool
def back_up_data(folder: str | None = None) -> dict:
    """Make a backup copy of the person's data: every profile, chart, life
    event and journal entry, in one dated file.

    Call it when they ask for a backup, and offer it after a session that
    added a lot. With no `folder` the copy goes to their usual backup folder.
    Pass `folder` only when they name somewhere themselves -- a USB stick, a
    second drive, a cloud-synced folder -- as a full path.

    The copy is whole even while the database is in use. A second backup on
    the same day replaces that day's file; earlier days are kept. Tell them
    where the file went, and that a copy on the same disk as the original
    guards against mistakes but not against the computer failing.
    """
    from . import backup
    store = _get_store()
    if store.shared:
        raise ToolError("Backups of the shared server are made by whoever "
                        "runs it, not from here.")
    result = backup.run(src=store.path, dest=folder or None)
    if not result["ok"]:
        raise ToolError(result["message"])
    return {"backed_up": True, "file": result["file"],
            "profiles": len(store.people()),
            "to_restore": "Close Claude, then copy this file over "
                          f"{store.path} (keeping that name)."}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
