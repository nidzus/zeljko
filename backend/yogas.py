"""Aspects, and the classical combinations a chart is actually about.

Without this the advisor has to spot combinations from raw positions, which it
will do inconsistently -- noticing a raja yoga one session and missing it the
next. Detecting them in code makes the reading of a chart stable.

Only well-defined combinations are here. Where a definition genuinely varies
between schools the variant used is named in the finding itself, so a reading
never rests on a choice the person cannot see.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import ephemeris, strength

KENDRAS = (1, 4, 7, 10)     # angles
TRIKONAS = (1, 5, 9)        # trines
DUSTHANAS = (6, 8, 12)      # the difficult houses

# Every graha aspects the seventh from itself. Three have extra aspects.
SPECIAL_ASPECTS = {"Mars": (4, 7, 8), "Jupiter": (5, 7, 9), "Saturn": (3, 7, 10)}
NODE_ASPECTS = (5, 7, 9)    # disputed; noted wherever it is relied on
BENEFICS = ("Jupiter", "Venus", "Mercury")


def aspect_offsets(body: str) -> tuple[int, ...]:
    """Which houses, counted from itself, this graha throws its aspect on."""
    if body in SPECIAL_ASPECTS:
        return SPECIAL_ASPECTS[body]
    if body in ("Rahu", "Ketu"):
        return NODE_ASPECTS
    return (7,)


def aspected_houses(chart: ephemeris.Chart, body: str) -> list[int]:
    """The houses of the chart this graha aspects."""
    house = chart.get(body).house
    return sorted(((house + off - 1 - 1) % 12) + 1 for off in aspect_offsets(body))


def aspects_house(chart: ephemeris.Chart, body: str, house: int) -> bool:
    return house in aspected_houses(chart, body)


def mutual_aspect(chart: ephemeris.Chart, a: str, b: str) -> bool:
    return (aspects_house(chart, a, chart.get(b).house)
            and aspects_house(chart, b, chart.get(a).house))


def conjunct(chart: ephemeris.Chart, a: str, b: str) -> bool:
    return chart.get(a).sign_index == chart.get(b).sign_index


def house_lord(chart: ephemeris.Chart, house: int) -> str:
    return strength.SIGN_LORD[chart.sign_in_house(house)]


def houses_ruled(chart: ephemeris.Chart, body: str) -> list[int]:
    return [h for h in range(1, 13) if house_lord(chart, h) == body]


def exchange(chart: ephemeris.Chart, a: str, b: str) -> bool:
    """Parivartana: each sits in a sign the other rules."""
    return (chart.get(a).house in houses_ruled(chart, b)
            and chart.get(b).house in houses_ruled(chart, a))


@dataclass
class Yoga:
    name: str
    kind: str            # raja | dhana | mahapurusha | lunar | affliction | other
    involves: list[str]
    meaning: str
    detail: str
    caveat: str = ""

    def as_dict(self) -> dict:
        d = {"name": self.name, "kind": self.kind, "involves": self.involves,
             "meaning": self.meaning, "detail": self.detail}
        if self.caveat:
            d["caveat"] = self.caveat
        return d


MAHAPURUSHA = {"Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa",
               "Venus": "Malavya", "Saturn": "Sasa"}


def _mahapurusha(chart, found):
    for body, name in MAHAPURUSHA.items():
        p = chart.get(body)
        if p.house not in KENDRAS:
            continue
        dignity, note = strength._dignity(body, p.sign_index, p.degrees_in_sign)
        if dignity in ("exalted", "own sign", "moolatrikona"):
            found.append(Yoga(
                name=f"{name} yoga", kind="mahapurusha", involves=[body],
                meaning=f"{body} is one of the chart's defining strengths, and "
                        f"what it governs tends to come good on its own terms.",
                detail=f"{body} {note}, in the {p.house}th house -- an angle."))


def _lunar(chart, found):
    """What sits either side of the Moon shapes how supported a life feels."""
    moon_house = chart.get("Moon").house
    second = (moon_house % 12) + 1
    twelfth = ((moon_house - 2) % 12) + 1
    others = [p.name for p in chart.positions
              if p.name not in ("Moon", "Sun", "Rahu", "Ketu")]
    in_second = [b for b in others if chart.get(b).house == second]
    in_twelfth = [b for b in others if chart.get(b).house == twelfth]

    if in_second and in_twelfth:
        found.append(Yoga(
            name="Durudhara yoga", kind="lunar",
            involves=sorted(set(in_second + in_twelfth)),
            meaning="Support on both sides of the Moon: resources and help tend "
                    "to be there when needed.",
            detail=f"{', '.join(in_twelfth)} in the 12th from the Moon and "
                   f"{', '.join(in_second)} in the 2nd."))
    elif in_second:
        found.append(Yoga(
            name="Sunapha yoga", kind="lunar", involves=in_second,
            meaning="Self-earned means; what is built tends to be built rather "
                    "than inherited.",
            detail=f"{', '.join(in_second)} in the 2nd from the Moon."))
    elif in_twelfth:
        found.append(Yoga(
            name="Anapha yoga", kind="lunar", involves=in_twelfth,
            meaning="An easier temperament and a tendency to be provided for.",
            detail=f"{', '.join(in_twelfth)} in the 12th from the Moon."))
    else:
        found.append(Yoga(
            name="Kemadruma yoga", kind="affliction", involves=["Moon"],
            meaning="The Moon stands unsupported, which classically reads as "
                    "periods of feeling on your own with things.",
            detail="Nothing but the Sun and the nodes flanks the Moon.",
            caveat="Widely held to be cancelled by benefics in angles from the "
                   "Moon or the lagna, so it is rarely as severe as its name. "
                   "Treat it as a note, not a verdict."))


def _raja_and_dhana(chart, found):
    kendra_lords = {house_lord(chart, h) for h in KENDRAS}
    trikona_lords = {house_lord(chart, h) for h in TRIKONAS}

    for k in sorted(kendra_lords):
        for t in sorted(trikona_lords):
            if k == t:
                continue
            how = ("conjunct" if conjunct(chart, k, t)
                   else "in mutual aspect" if mutual_aspect(chart, k, t)
                   else "in exchange" if exchange(chart, k, t) else None)
            if how:
                # A participant that also rules a difficult house qualifies the
                # yoga. Classical practice says so, and leaving it out would
                # overstate a combination the chart only half carries.
                tainted = sorted({b for b in (k, t)
                                  if set(houses_ruled(chart, b)) & set(DUSTHANAS)})
                caveat = ""
                if tainted:
                    caveat = (f"{' and '.join(tainted)} also rules a difficult "
                              f"house, which classically qualifies the yoga -- "
                              f"the rise tends to come with a cost attached "
                              f"rather than cleanly.")
                found.append(Yoga(
                    name="Raja yoga", kind="raja", involves=sorted([k, t]),
                    meaning="A capacity to rise: an angle and a trine of the "
                            "chart working together rather than separately.",
                    detail=f"{k}, lord of "
                           f"{', '.join(str(h) for h in houses_ruled(chart, k))}, "
                           f"and {t}, lord of "
                           f"{', '.join(str(h) for h in houses_ruled(chart, t))}, "
                           f"are {how}.",
                    caveat=caveat))

    wealth = {house_lord(chart, h) for h in (2, 11)}
    support = {house_lord(chart, h) for h in (1, 5, 9)}
    for w in sorted(wealth):
        for s in sorted(support):
            if w == s:
                continue
            if conjunct(chart, w, s) or mutual_aspect(chart, w, s):
                found.append(Yoga(
                    name="Dhana yoga", kind="dhana", involves=sorted([w, s]),
                    meaning="Accumulation is supported; money tends to arrive "
                            "through the areas these two govern.",
                    detail=f"{w} and {s} are "
                           f"{'conjunct' if conjunct(chart, w, s) else 'in mutual aspect'}."))


def _vipareeta(chart, found):
    for house in DUSTHANAS:
        lord = house_lord(chart, house)
        where = chart.get(lord).house
        if where in DUSTHANAS and where != house:
            found.append(Yoga(
                name="Vipareeta Raja yoga", kind="raja", involves=[lord],
                meaning="Difficulty turning to advantage: gains that arrive "
                        "through trouble rather than despite it.",
                detail=f"{lord}, lord of the {house}th, sits in the {where}th -- "
                       f"both difficult houses, which cancels rather than "
                       f"compounds."))


def _other(chart, found):
    jup, moon = chart.get("Jupiter"), chart.get("Moon")
    offset = ((jup.house - moon.house) % 12) + 1
    if offset in KENDRAS:
        found.append(Yoga(
            name="Gajakesari yoga", kind="other", involves=["Jupiter", "Moon"],
            meaning="Judgement and standing: the capacity to be listened to.",
            detail=f"Jupiter is in the {offset}th house from the Moon, an angle."))

    if conjunct(chart, "Sun", "Mercury"):
        p = chart.get("Mercury")
        combust, note = strength._combustion(
            "Mercury", p.longitude, chart.get("Sun").longitude, p.retrograde)
        found.append(Yoga(
            name="Budha-Aditya yoga", kind="other", involves=["Sun", "Mercury"],
            meaning="Intelligence applied to what the Sun governs -- clarity, "
                    "articulacy, being good at explaining things.",
            detail=f"Sun and Mercury together in {p.sign_english}.",
            caveat=("Mercury is combust here, which many read as undercutting "
                    "the yoga considerably." if combust else "")))

    if conjunct(chart, "Moon", "Mars"):
        found.append(Yoga(
            name="Chandra-Mangala yoga", kind="dhana",
            involves=["Moon", "Mars"],
            meaning="Drive attached to feeling: enterprising with money, and "
                    "inclined to act on instinct about it.",
            detail=f"Moon and Mars together in {chart.get('Moon').sign_english}."))

    for benefic in BENEFICS:
        if chart.get(benefic).house == 10:
            found.append(Yoga(
                name="Amala yoga", kind="other", involves=[benefic],
                meaning="A clean reputation: what you are known for tends to "
                        "hold up to scrutiny.",
                detail=f"{benefic}, a natural benefic, occupies the 10th."))
            break

    off = ((moon.house - jup.house) % 12) + 1
    if off in DUSTHANAS:
        found.append(Yoga(
            name="Shakata yoga", kind="affliction", involves=["Moon", "Jupiter"],
            meaning="Fortune that rises and falls rather than accumulating "
                    "steadily.",
            detail=f"The Moon is in the {off}th from Jupiter.",
            caveat="Commonly held not to apply when Jupiter is in an angle from "
                   "the lagna. Check before weighting it."))


def _kala_sarpa(chart, found):
    rahu = chart.get("Rahu").longitude
    ketu = chart.get("Ketu").longitude
    others = [p for p in chart.positions if p.name not in ("Rahu", "Ketu")]
    # Measure each graha's distance forward from Rahu; all on one side means
    # all fall within the semicircle before Ketu.
    spans = [(p.longitude - rahu) % 360 for p in others]
    if all(s < 180 for s in spans) or all(s > 180 for s in spans):
        found.append(Yoga(
            name="Kala Sarpa yoga", kind="affliction",
            involves=["Rahu", "Ketu"],
            meaning="Every graha falls on one side of the nodal axis, which "
                    "classically reads as a life that moves in long blocked "
                    "stretches followed by sudden release.",
            detail=f"All seven grahas lie between Rahu at "
                   f"{ephemeris.dms(rahu % 30)} and Ketu at "
                   f"{ephemeris.dms(ketu % 30)}.",
            caveat="Modern authorities differ sharply on whether this is a real "
                   "affliction at all. Mention it; do not build an answer on it."))


def _neecha_bhanga(chart, found):
    for p in chart.positions:
        if p.name in ("Rahu", "Ketu"):
            continue
        dignity, _ = strength._dignity(p.name, p.sign_index, p.degrees_in_sign)
        if dignity != "debilitated":
            continue
        lord = strength.SIGN_LORD[p.sign_index]
        lord_house = chart.get(lord).house
        moon_house = chart.get("Moon").house
        from_moon = ((lord_house - moon_house) % 12) + 1
        if lord_house in KENDRAS or from_moon in KENDRAS:
            found.append(Yoga(
                name="Neecha Bhanga", kind="other", involves=[p.name, lord],
                meaning=f"{p.name}'s debilitation is cancelled, so the weakness "
                        f"tends to be recovered from rather than lived with.",
                detail=f"{p.name} is debilitated in {p.sign_english}, but "
                       f"{lord}, which rules that sign, sits in an angle.",
                caveat="One of several classical definitions of cancellation; "
                       "others require different conditions."))


def detect(chart: ephemeris.Chart) -> list[Yoga]:
    """Every combination this chart carries, from the set covered here."""
    found: list[Yoga] = []
    _mahapurusha(chart, found)
    _lunar(chart, found)
    _raja_and_dhana(chart, found)
    _vipareeta(chart, found)
    _other(chart, found)
    _kala_sarpa(chart, found)
    _neecha_bhanga(chart, found)
    return found
