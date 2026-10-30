"""The tools the advisor is allowed to use, and nothing else.

Two ideas do the real work here.

**The gate is enforced, not requested.** A tool that would return something the
birth time cannot support refuses. The model is never asked to remember the
rule, because a rule a model is asked to remember is a rule it can forget.

**Precision is removed at source.** When a birth time only supports dates to
the month, the dasha tool returns "November 2026" -- not a date that was
rounded in the wording afterwards. The model cannot state a false precision
because it never sees one.

Every result carries a fact id. Claims in the answer cite those ids, and the
ids are checked afterwards against what was actually returned.
"""
from __future__ import annotations

from datetime import datetime, timezone

import swisseph as swe

from . import divisional, ephemeris, transits
from .store import Store

VARGA_CLAIM = {9: "navamsa", 60: "shashtiamsa"}
VARGA_NAME = {9: "Navamsa (D-9)", 60: "Shashtiamsa (D-60)"}


def _jd(iso: str) -> float:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute / 60 + dt.second / 3600)


def format_date(dt: datetime, precision: str) -> str:
    """State a date only as precisely as the birth time can support."""
    if precision == "exact dates":
        return dt.strftime("%Y-%m-%d")
    if precision == "to the week":
        return f"the week of {dt:%d %B %Y}"
    if precision == "to the month":
        return dt.strftime("%B %Y")
    if precision == "to the season":
        part = "early" if dt.month <= 4 else "mid" if dt.month <= 8 else "late"
        return f"{part} {dt.year}"
    return "date not supportable"


SCHEMAS = [
    {
        "name": "dasha_at",
        "description": (
            "The Vimshottari periods running at a date, nested three deep "
            "(mahadasha, antardasha, pratyantardasha). Dates are returned only "
            "as precisely as this chart's birth time supports."),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string",
                         "description": "ISO date, e.g. 2026-11-15"},
            },
            "required": ["date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "transits_at",
        "description": (
            "Where each graha is transiting at a date, and which house of THIS "
            "nativity it occupies. Includes degree within the sign and whether "
            "it is retrograde, so you can tell a graha just arrived from one "
            "about to leave."),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "ISO date"},
            },
            "required": ["date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "events_between",
        "description": (
            "Every moment between two dates where this nativity's situation "
            "changes: sign ingresses (with the house entered), retrograde and "
            "direct stations, and dasha handovers. These are the only points "
            "at which a judgement can change."),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "ISO date"},
                "end": {"type": "string", "description": "ISO date"},
                "bodies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("Optional subset, e.g. ['Jupiter','Saturn']. "
                                    "Omit for all nine."),
                },
            },
            "required": ["start", "end"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "divisional_chart",
        "description": (
            "A divisional chart. 10 is the dasamsa, read for career and "
            "standing; 9 the navamsa, for marriage and how a placement really "
            "behaves; 4 property, 7 children, 3 siblings and initiative, 2 "
            "wealth, 12 parents, 30 misfortune, 60 the finest division. Each "
            "has its own tolerance and refuses when the birth time cannot "
            "support it, which is common and is not an error."),
        "input_schema": {
            "type": "object",
            "properties": {
                "varga": {"type": "integer",
                          "enum": [1, 2, 3, 4, 7, 9, 10, 12, 30, 60]},
            },
            "required": ["varga"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


class ToolRunner:
    """Executes tool calls against one person's chart, recording every fact."""

    def __init__(self, store: Store, person_id: int):
        self.store = store
        self.person_id = person_id
        self.row = store.active_chart_row(person_id)
        self.chart = store.compute(self.row)
        self.tree = store.dasha_tree(self.row, levels=3)
        self.reliability = store.reliability(self.row)
        self.facts: dict[str, dict] = {}
        self._n = 0

    # ------------------------------------------------------------- recording

    def _record(self, kind: str, payload: dict) -> dict:
        self._n += 1
        fact_id = f"f{self._n}"
        self.facts[fact_id] = {"fact_id": fact_id, "kind": kind, **payload}
        return self.facts[fact_id]

    # ----------------------------------------------------------------- tools

    def dasha_at(self, date: str) -> dict:
        precision = self.reliability.date_precision
        if precision == "none":
            return self._record("dasha", {
                "refused": True,
                "reason": ("This birth time does not support dasha dates at "
                           "all -- the Moon's nakshatra itself is uncertain, "
                           "so the sequence of lords could be wrong. "
                           "Rectification is needed before any timing claim."),
            })
        chain = self.tree.at(_jd(date))
        return self._record("dasha", {
            "date": date,
            "date_precision": precision,
            "periods": [
                {"level": ["", "mahadasha", "antardasha",
                           "pratyantardasha"][p.level],
                 "lord": p.lord,
                 "begins": format_date(p.start, precision),
                 "ends": format_date(p.end, precision)}
                for p in chain],
        })

    def transits_at(self, date: str) -> dict:
        jd = _jd(date)
        out = []
        for name, _sanskrit, _code in ephemeris.GRAHAS:
            out.append(self._transit(name, jd))
        out.append(self._transit("Ketu", jd))
        return self._record("transit", {"date": date, "positions": out})

    def _transit(self, body: str, jd: float) -> dict:
        longitude, speed = transits.state(jd, body, self.row["ayanamsa"])
        sign_index = int(longitude // 30)
        degrees = longitude - sign_index * 30
        return {
            "body": body,
            "sign": ephemeris.SIGNS[sign_index][1],
            "degrees_in_sign": round(degrees, 2),
            # Whether a graha just arrived or is about to leave is usually the
            # whole answer, and is what a bare "Saturn is in your 10th" hides.
            "house_of_nativity": self.chart.house_of(sign_index),
            "retrograde": speed < 0,
            "daily_motion": round(speed, 4),
        }

    def events_between(self, start: str, end: str,
                       bodies: list[str] | None = None) -> dict:
        precision = self.reliability.date_precision
        known = {n for n, _, _ in ephemeris.GRAHAS} | {"Ketu"}
        if bodies:
            unknown = set(bodies) - known
            if unknown:
                return self._record("events", {
                    "refused": True,
                    "reason": f"Unknown bodies: {sorted(unknown)}. "
                              f"Available: {sorted(known)}",
                })
        events = transits.timeline(self.chart, self.tree, _jd(start), _jd(end),
                                   bodies=bodies or None, dasha_levels=2)
        rows = []
        for e in events:
            # Transit dates are astronomy and stand on their own. Dasha dates
            # depend on the birth time, so they inherit its precision.
            when = (format_date(e.when, precision) if e.kind == "dasha"
                    else e.when.strftime("%Y-%m-%d"))
            if e.kind == "dasha" and precision == "none":
                continue
            rows.append({"when": when, "kind": e.kind, "body": e.body,
                         "detail": e.detail,
                         **({"house": e.house} if e.house else {})})
        return self._record("events", {
            "start": start, "end": end,
            "dasha_date_precision": precision,
            "events": rows,
        })

    def divisional_chart(self, varga: int) -> dict:
        if varga not in divisional.VARGAS:
            return self._record("divisional", {
                "refused": True,
                "reason": f"D-{varga} is not supported. Available: "
                          f"{sorted(divisional.VARGAS)}"})

        name, read_for = divisional.VARGAS[varga]

        # Structural refusal. Each varga has its own tolerance -- the D-30
        # slices a sign into single degrees -- so this is checked per chart and
        # per varga, not by a blanket rule.
        if not self.reliability.allows_varga(varga):
            return self._record("divisional", {
                "refused": True,
                "varga": f"D-{varga}",
                "name": name,
                "reason": (
                    f"The {name} (D-{varga}) is not supportable for this "
                    f"chart. The birth time is known to about "
                    f"±{self.reliability.window_minutes} minutes, and across "
                    f"that window its lagna changes. Say so plainly, and say "
                    f"what would fix it -- a more precise birth time, or "
                    f"rectification -- rather than reasoning from it."),
            })

        return self._record("divisional",
                            divisional.compute(self.chart, varga).as_dict())

    # -------------------------------------------------------------- dispatch

    def call(self, name: str, arguments: dict) -> dict:
        handler = {
            "dasha_at": self.dasha_at,
            "transits_at": self.transits_at,
            "events_between": self.events_between,
            "divisional_chart": self.divisional_chart,
        }.get(name)
        if handler is None:
            return {"error": f"No such tool: {name}"}
        try:
            return handler(**arguments)
        except (TypeError, ValueError) as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
