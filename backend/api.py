"""HTTP layer. The browser talks to this; nothing else does.

Runs on localhost only. No authentication, because there is no network
surface: these are profiles you manage on your own machine. It opens the
personal database as its owner and has nothing to do with the shared server.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import swisseph as swe
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import coords, dasha, ephemeris, timeplace, transits
from .confidence import TimeConfidence
from .store import CLAIM_KINDS, Store

app = FastAPI(title="Jyotisha advisor", docs_url="/api/docs")

FRONTEND = Path(__file__).parent.parent / "frontend"


@app.exception_handler(KeyError)
def _not_found(request, exc: KeyError):
    # The store raises KeyError for an id it does not hold.
    return JSONResponse({"detail": str(exc.args[0]) if exc.args else "not found"},
                        status_code=404)


def get_store():
    # A short-lived connection per request. SQLite opens in microseconds, and
    # this sidesteps sharing one handle across FastAPI's thread pool.
    with Store() as store:
        yield store


def iso_to_jd(iso: str) -> float:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute / 60 + dt.second / 3600)


def jd_to_iso(jd: float) -> str:
    return dasha.jd_to_datetime(jd).isoformat()


# ------------------------------------------------------------------ payloads


class PersonIn(BaseModel):
    name: str = Field(min_length=1)
    relation: str = "self"
    notes: str = ""


class CoordsIn(BaseModel):
    text: str


class BirthIn(BaseModel):
    """One onboarding submission."""
    year: int
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    second: int = Field(default=0, ge=0, le=59)
    place_name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    time_confidence: str
    ayanamsa: str = "LAHIRI"
    derived_from_id: int | None = None
    rectification_note: str | None = None


class EventIn(BaseModel):
    happened_on: str
    title: str = Field(min_length=1)
    precision: str = "day"
    category: str | None = None
    description: str = ""
    significance: int = Field(default=3, ge=1, le=5)


# -------------------------------------------------------------- places first


@app.get("/api/places")
def search_places(q: str = Query(min_length=2), limit: int = 10):
    """City search against a local database. Nothing leaves the machine."""
    return [{"name": p.name, "country": p.country, "latitude": p.latitude,
             "longitude": p.longitude, "population": p.population}
            for p in timeplace.search_places(q, limit)]


@app.post("/api/places/coords")
def parse_coords(body: CoordsIn):
    """Read pasted coordinates, in whichever format they arrive.

    The escape hatch for births the city database does not contain.
    """
    try:
        c = coords.parse(body.text)
    except coords.CoordinateError as e:
        raise HTTPException(422, str(e))
    return {"latitude": c.latitude, "longitude": c.longitude,
            "formatted": str(c),
            "timezone": timeplace.timezone_for(c.latitude, c.longitude)}


@app.get("/api/reference")
def reference():
    """Vocabulary the interface needs: confidence levels, ayanamsas, claims."""
    return {
        "time_confidence": [
            {"name": c.name, "description": c.description,
             "window_minutes": c.window_minutes} for c in TimeConfidence],
        "ayanamsas": sorted(ephemeris.AYANAMSAS),
        "claim_kinds": list(CLAIM_KINDS),
        "signs": [{"sanskrit": a, "english": b} for a, b in ephemeris.SIGNS],
    }


# ------------------------------------------------------------------- people


@app.get("/api/people")
def list_people(store: Store = Depends(get_store)):
    out = []
    for p in store.people():
        try:
            chart_row = store.active_chart_row(p["id"])
            has_chart, lagna = True, store.compute(chart_row).ascendant.sign_english
        except KeyError:
            has_chart, lagna = False, None
        out.append({"id": p["id"], "name": p["name"], "relation": p["relation"],
                    "has_chart": has_chart, "lagna": lagna})
    return out


@app.post("/api/people", status_code=201)
def create_person(body: PersonIn, store: Store = Depends(get_store)):
    pid = store.add_person(body.name, body.relation, body.notes)
    return {"id": pid}


@app.post("/api/people/{person_id}/chart", status_code=201)
def create_chart(person_id: int, body: BirthIn, store: Store = Depends(get_store)):
    """Onboarding. Also the path a rectified version takes."""
    try:
        conf = TimeConfidence[body.time_confidence]
    except KeyError:
        raise HTTPException(422, f"unknown time_confidence {body.time_confidence!r}")
    if body.ayanamsa not in ephemeris.AYANAMSAS:
        raise HTTPException(422, f"unknown ayanamsa {body.ayanamsa!r}")
    try:
        store.person(person_id)
    except KeyError:
        raise HTTPException(404, f"no person {person_id}")

    chart_id = store.add_chart(
        person_id, body.year, body.month, body.day, body.hour, body.minute,
        body.second, body.place_name, body.latitude, body.longitude, conf,
        body.ayanamsa, body.derived_from_id, body.rectification_note)

    row = store.active_chart_row(person_id)
    return {
        "id": chart_id,
        # Surfaced, never silently resolved: both need a human answer.
        "time_ambiguous": bool(row["time_ambiguous"]),
        "time_nonexistent": bool(row["time_nonexistent"]),
        "used_local_mean_time": bool(row["used_local_mean_time"]),
        "timezone_name": row["timezone_name"],
        "utc_offset_hours": row["utc_offset_hours"],
        "iana_offset_hours": row["iana_offset_hours"],
    }


def _chart_row(store: Store, person_id: int):
    try:
        return store.active_chart_row(person_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/people/{person_id}/chart")
def get_chart(person_id: int, store: Store = Depends(get_store)):
    row = _chart_row(store, person_id)
    chart = store.compute(row)
    rel = store.reliability(row)
    return {
        "birth": {
            "date": row["birth_date"], "time": row["birth_time"],
            "place": row["place_name"],
            "latitude": row["latitude"], "longitude": row["longitude"],
            "timezone": row["timezone_name"],
            "utc_offset_hours": row["utc_offset_hours"],
            "used_local_mean_time": bool(row["used_local_mean_time"]),
            "time_confidence": row["time_confidence"],
        },
        "ayanamsa": {"name": row["ayanamsa"],
                     "value": chart.ayanamsa_value,
                     "formatted": ephemeris.dms(chart.ayanamsa_value)},
        "lagna": _position(chart.ascendant),
        "positions": [_position(p) for p in chart.positions],
        "houses": [{"house": h,
                    "sign_index": chart.sign_in_house(h),
                    "sign": ephemeris.SIGNS[chart.sign_in_house(h)][0],
                    "sign_english": ephemeris.SIGNS[chart.sign_in_house(h)][1]}
                   for h in range(1, 13)],
        "reliability": _reliability(rel),
    }


def _position(p: ephemeris.Position) -> dict:
    return {"name": p.name, "sanskrit": p.sanskrit,
            "longitude": p.longitude, "speed": p.speed,
            "sign_index": p.sign_index, "sign": p.sign,
            "sign_english": p.sign_english,
            "degrees_in_sign": p.degrees_in_sign,
            "formatted": ephemeris.dms(p.degrees_in_sign),
            "nakshatra": p.nakshatra, "pada": p.pada,
            "house": p.house, "retrograde": p.retrograde}


def _reliability(rel) -> dict:
    return {"window_minutes": rel.window_minutes,
            "rasi_lagna_stable": rel.rasi_lagna_stable,
            "nakshatra_stable": rel.nakshatra_stable,
            "navamsa_stable": rel.navamsa_stable,
            "shashtiamsa_stable": rel.shashtiamsa_stable,
            "dasha_drift_days": rel.dasha_drift_days,
            "degrees_to_lagna_boundary": rel.degrees_to_lagna_boundary,
            "date_precision": rel.date_precision,
            "permitted": {k: rel.allows(k) for k in CLAIM_KINDS},
            "summary": rel.summary()}


@app.get("/api/people/{person_id}/charts")
def chart_versions(person_id: int, store: Store = Depends(get_store)):
    return [{"id": r["id"], "birth_date": r["birth_date"],
             "birth_time": r["birth_time"],
             "time_confidence": r["time_confidence"],
             "is_active": bool(r["is_active"]),
             "derived_from_id": r["derived_from_id"],
             "rectification_note": r["rectification_note"],
             "created_at": r["created_at"]}
            for r in store.chart_versions(person_id)]


# ------------------------------------------------------------- life events


@app.get("/api/people/{person_id}/events")
def list_events(person_id: int, store: Store = Depends(get_store)):
    return [dict(e) for e in store.life_events(person_id)]


@app.post("/api/people/{person_id}/events", status_code=201)
def create_event(person_id: int, body: EventIn, store: Store = Depends(get_store)):
    try:
        eid = store.add_life_event(
            person_id, body.happened_on, body.title, body.precision,
            body.category, body.description, body.significance)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": eid}


# ------------------------------------------------------- dasha and timeline


@app.get("/api/people/{person_id}/dasha")
def get_dasha(person_id: int, at: str | None = None,
              store: Store = Depends(get_store)):
    """The nested periods running at a moment, plus the mahadasha sequence."""
    row = _chart_row(store, person_id)
    tree = store.dasha_tree(row, levels=3)
    jd = iso_to_jd(at) if at else iso_to_jd(datetime.now(timezone.utc).isoformat())
    rel = store.reliability(row)

    def serialize(p):
        return {"lord": p.lord, "level": p.level,
                "start": jd_to_iso(p.start_jd), "end": jd_to_iso(p.end_jd),
                "length_days": p.length_days}

    return {
        "at": jd_to_iso(jd),
        "running": [serialize(p) for p in tree.at(jd)],
        "mahadashas": [serialize(p) for p in tree.periods[:9]],
        "balance_years_at_birth": tree.balance_years,
        # How precisely these dates may be quoted, given the birth time.
        "date_precision": rel.date_precision,
    }


@app.get("/api/people/{person_id}/timeline")
def get_timeline(person_id: int, start: str, end: str,
                 bodies: str | None = None, dasha_levels: int = 2,
                 store: Store = Depends(get_store)):
    """Every moment in the window where this nativity's situation changes."""
    row = _chart_row(store, person_id)
    chart = store.compute(row)
    tree = store.dasha_tree(row, levels=max(2, dasha_levels))
    selected = [b.strip() for b in bodies.split(",")] if bodies else None
    if selected:
        known = {n for n, _, _ in ephemeris.GRAHAS} | {"Ketu"}
        unknown = set(selected) - known
        if unknown:
            raise HTTPException(422, f"unknown bodies: {sorted(unknown)}")

    events = transits.timeline(chart, tree, iso_to_jd(start), iso_to_jd(end),
                               bodies=selected, dasha_levels=dasha_levels)
    return [{"kind": e.kind, "when": jd_to_iso(e.jd), "body": e.body,
             "detail": e.detail, "house": e.house, "sign_index": e.sign_index}
            for e in events]


@app.get("/api/people/{person_id}/context")
def get_context(person_id: int, store: Store = Depends(get_store)):
    """The cacheable prefix, exposed so it can be inspected rather than trusted."""
    _chart_row(store, person_id)
    text = store.context_prefix(person_id)
    return {"text": text, "bytes": len(text.encode())}


# ------------------------------------------------------- the decision journal


class ChoiceIn(BaseModel):
    chose: str = Field(min_length=1)


class OutcomeIn(BaseModel):
    outcome: str = Field(min_length=1)
    rating: int = Field(ge=-2, le=2)


@app.get("/api/people/{person_id}/decisions")
def list_decisions(person_id: int, store: Store = Depends(get_store)):
    """The journal: what was asked, advised, chosen, and how it turned out."""
    out = []
    for r in reversed(store.decisions(person_id)):
        out.append({
            "id": r["id"], "asked_at": r["asked_at"], "question": r["question"],
            "question_type": r["question_type"], "verdict": r["verdict"],
            "confidence": r["confidence"],
            "window_opens": r["window_opens"], "window_closes": r["window_closes"],
            "chose": r["chose"], "chose_at": r["chose_at"],
            "outcome": r["outcome"], "outcome_rating": r["outcome_rating"],
            "citations": len(store.citations(r["id"])),
            # Open loops are the point: a decision with no outcome yet is
            # something to come back to, not something finished.
            "open": r["outcome"] is None,
        })
    return out


@app.get("/api/decisions/{decision_id}")
def get_decision(decision_id: int, store: Store = Depends(get_store)):
    try:
        row = store.decision(decision_id)
    except KeyError:
        raise HTTPException(404, f"no decision {decision_id}")
    return {**row,
            "citations": [dict(c) for c in store.citations(decision_id)]}


@app.post("/api/decisions/{decision_id}/choice")
def set_choice(decision_id: int, body: ChoiceIn,
               store: Store = Depends(get_store)):
    try:
        store.record_choice(decision_id, body.chose)
    except KeyError:
        raise HTTPException(404, f"no decision {decision_id}")
    return {"id": decision_id, "chose": body.chose}


@app.post("/api/decisions/{decision_id}/outcome")
def set_outcome(decision_id: int, body: OutcomeIn,
                store: Store = Depends(get_store)):
    """Closing the loop. This is what turns the journal into an eval set."""
    try:
        store.record_outcome(decision_id, body.outcome, body.rating)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except KeyError:
        raise HTTPException(404, f"no decision {decision_id}")
    return {"id": decision_id, "outcome": body.outcome, "rating": body.rating}


# ------------------------------------------------------------------ frontend

if FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
