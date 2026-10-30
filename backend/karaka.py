"""Testing a birth time on WHICH lords were running, not just when.

The timing test in rectify.py asks whether a life event fell near a dasha
boundary. That is weak, because antardasha boundaries are dense enough that
proximity is cheap -- the null model put a real chart only 2.4 sigma above
randomised dates.

This asks a harder question: when your father died, was the Sun running, or
the lord of the 9th? When you married, was it Venus or the 7th lord? A wrong
birth time can put a boundary near a date by luck. Putting the RIGHT lord
there, repeatedly, across many events, is much harder to do by accident.

The rules below are the standard significators. They are stated as data rather
than buried in code so they can be argued with, which matters: the whole method
is only as good as the mapping, and a chart is not evidence for a mapping that
was chosen to fit it.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import dasha, ephemeris, yogas

# Each rule: keywords that identify the kind of event, the houses that govern
# it, and the natural significators. An event matches if the running mahadasha
# or antardasha lord is a lord of one of those houses, or one of the karakas.
RULES = [
    # (name, keywords, categories, houses, karakas)
    ("father", ("father", "dad", "otac"), (), (9,), ("Sun",)),
    ("mother", ("mother", "mum", "mom", "majka"), (), (4,), ("Moon",)),
    ("marriage", ("married", "marriage", "wedding", "engaged"),
     ("marriage",), (7,), ("Venus",)),
    ("separation", ("divorce", "separated", "split"), (), (7,), ("Venus", "Saturn")),
    ("children", ("born", "birth", "daughter", "son", "child", "pregnan"),
     (), (5,), ("Jupiter",)),
    ("career", ("job", "work", "career", "engagement", "employ", "hired",
                "promoted", "redundan", "fired", "unemploy", "business",
                "founded", "startup"),
     ("career",), (10, 6), ("Saturn", "Sun")),
    ("study", ("stud", "school", "mba", "degree", "university", "enrol",
               "graduat", "course"),
     ("education",), (4, 5), ("Mercury", "Jupiter")),
    ("money", ("money", "loan", "debt", "bought", "sold", "invest",
               "inherit", "salary", "savings"),
     ("finance",), (2, 11), ("Jupiter", "Venus")),
    ("property", ("house", "flat", "apartment", "property", "land", "home"),
     ("property",), (4,), ("Mars",)),
    ("relocation", ("moved", "relocat", "emigrat", "immigrat", "green card",
                    "visa", "abroad"),
     ("relocation", "immigration"), (12, 9, 4), ("Moon", "Rahu")),
    ("health", ("ill", "illness", "surgery", "operation", "hospital",
                "stroke", "diagnos", "accident", "injur"),
     ("health",), (6, 1, 8), ("Sun", "Saturn")),
    ("death", ("died", "death", "passed away", "funeral"), (), (8,), ("Saturn",)),
]


@dataclass
class EventFit:
    event: str
    happened_on: str
    rule: str
    expected: list[str]
    running: list[str]
    matched: bool
    weight: float


def expectations(chart: ephemeris.Chart, event: dict) -> tuple[str, set[str]]:
    """Which lords ought to be running when this kind of thing happens."""
    text = f"{event['title']} {event.get('description') or ''}".lower()
    category = (event.get("category") or "").lower()

    names, houses, karakas = [], set(), set()
    for name, keywords, categories, rule_houses, rule_karakas in RULES:
        if any(k in text for k in keywords) or (category and category in categories):
            names.append(name)
            houses.update(rule_houses)
            karakas.update(rule_karakas)

    # A parent's death is about the parent, not about death in the abstract.
    if "father" in names and "death" in names:
        names, houses, karakas = ["father (death)"], {9}, {"Sun"}
    elif "mother" in names and "death" in names:
        names, houses, karakas = ["mother (death)"], {4}, {"Moon"}

    if not names:
        return "", set()
    expected = {yogas.house_lord(chart, h) for h in houses} | karakas
    return "+".join(names), expected


def fit(chart: ephemeris.Chart, tree: dasha.DashaTree,
        events: list[dict]) -> dict:
    """How often the right lords were running, across a person's whole life."""
    rows, matched_weight, total_weight = [], 0.0, 0.0
    # A year-dated event still lands inside the right antardasha most of the
    # time -- those run one to three years -- but it deserves less weight.
    precision_weight = {"day": 1.0, "month": 0.85, "year": 0.5}

    for e in events:
        rule, expected = expectations(chart, e)
        if not expected:
            continue                       # nothing classical to test against
        y, m, d = (int(x) for x in e["happened_on"].split("-"))
        chain = tree.at(dasha.swe.julday(y, m, d, 12.0))
        if not chain:
            continue
        running = [p.lord for p in chain[:2]]
        hit = bool(set(running) & expected)
        weight = (e["significance"] / 3.0) * precision_weight.get(
            e["precision"], 0.85)
        total_weight += weight
        if hit:
            matched_weight += weight
        rows.append(EventFit(event=e["title"][:44],
                             happened_on=e["happened_on"], rule=rule,
                             expected=sorted(expected), running=running,
                             matched=hit, weight=round(weight, 2)))

    return {
        "events_testable": len(rows),
        "matched": sum(1 for r in rows if r.matched),
        "score": round(matched_weight / total_weight, 3) if total_weight else 0.0,
        "detail": rows,
    }


def baseline(chart: ephemeris.Chart, events: list[dict]) -> float:
    """What score a chart would get by chance.

    Two of nine lords are running at any moment, so a rule naming k distinct
    expected lords hits by luck roughly as often as those overlap. Without
    this the raw score looks impressive when it is merely arithmetic.
    """
    total, weighted = 0.0, 0.0
    precision_weight = {"day": 1.0, "month": 0.85, "year": 0.5}
    for e in events:
        _rule, expected = expectations(chart, e)
        if not expected:
            continue
        weight = (e["significance"] / 3.0) * precision_weight.get(
            e["precision"], 0.85)
        # P(at least one of 2 running lords falls in the expected set of size k)
        k = len(expected & {n for n, _, _ in ephemeris.GRAHAS} | expected)
        k = min(len(expected), 9)
        p = 1 - ((9 - k) / 9) * ((8 - k) / 8 if k < 9 else 0)
        total += weight
        weighted += weight * p
    return round(weighted / total, 3) if total else 0.0
