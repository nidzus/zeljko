"""Turning "born in Belgrade at 4:30pm on 12 March 1988" into an exact instant.

This is where charts go wrong silently. A birth time is a *local wall-clock*
reading, and converting it to a real moment needs the timezone rules that were
in force on that date -- not today's. Countries have changed zones, abolished
DST, and kept wartime offsets. Get it wrong by an hour and the ascendant can
move a whole sign, with nothing anywhere to warn you.

So we resolve through the IANA database at the birth date, and we record what
we used, so it can always be audited later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from geonamescache import GeonamesCache
from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()
_gc = GeonamesCache()


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    latitude: float
    longitude: float
    population: int

    def __str__(self) -> str:
        return f"{self.name}, {self.country} ({self.latitude:.4f}, {self.longitude:.4f})"


@dataclass(frozen=True)
class ResolvedMoment:
    """A birth moment, with every step of the conversion preserved."""

    local_input: str          # exactly what the user typed
    timezone_name: str        # IANA zone, e.g. "Europe/Belgrade"
    utc_offset_hours: float   # the offset actually applied
    iana_offset_hours: float  # what the IANA database alone would have given
    used_local_mean_time: bool  # true when we overrode IANA (see resolve())
    utc: datetime             # the resulting instant
    julian_day_ut: float      # what Swiss Ephemeris consumes
    ambiguous: bool           # local time occurred twice (DST fall-back)
    nonexistent: bool         # local time never occurred (DST spring-forward)

    @property
    def needs_attention(self) -> bool:
        return self.ambiguous or self.nonexistent


def search_places(query: str, limit: int = 10) -> list[Place]:
    """Find candidate birthplaces from a local database. Nothing leaves the machine."""
    q = query.strip().lower()
    hits = [
        Place(
            name=c["name"],
            country=c["countrycode"],
            latitude=float(c["latitude"]),
            longitude=float(c["longitude"]),
            population=int(c["population"]),
        )
        for c in _gc.get_cities().values()
        if c["name"].lower() == q
    ]
    if not hits:
        hits = [
            Place(
                name=c["name"],
                country=c["countrycode"],
                latitude=float(c["latitude"]),
                longitude=float(c["longitude"]),
                population=int(c["population"]),
            )
            for c in _gc.get_cities().values()
            if q in c["name"].lower()
        ]
    # Bigger places first: the likeliest match for a bare city name.
    hits.sort(key=lambda p: p.population, reverse=True)
    return hits[:limit]


def timezone_for(latitude: float, longitude: float) -> str:
    """Which IANA timezone governs this point on the earth."""
    name = _tf.timezone_at(lat=latitude, lng=longitude)
    if name is None:
        raise ValueError(f"No timezone found for ({latitude}, {longitude})")
    return name


def resolve(
    year: int, month: int, day: int, hour: int, minute: int,
    latitude: float, longitude: float,
    timezone_name: str | None = None,
    second: int = 0,
) -> ResolvedMoment:
    """Convert a local birth time into an exact UTC instant, auditably."""
    tzname = timezone_name or timezone_for(latitude, longitude)
    tz = ZoneInfo(tzname)

    naive = datetime(year, month, day, hour, minute, second)

    # fold=0 and fold=1 pick the two readings of an ambiguous local time.
    # If they disagree, this wall-clock reading happened twice that day.
    first = naive.replace(tzinfo=tz, fold=0)
    second = naive.replace(tzinfo=tz, fold=1)
    ambiguous = first.utcoffset() != second.utcoffset()

    # A time inside a spring-forward gap never existed. Round-tripping through
    # UTC lands somewhere else, which is how we detect it.
    nonexistent = first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != naive

    # Before a region adopted standard time, IANA represents the period using
    # the local mean time of the ZONE'S REFERENCE CITY -- e.g. 1869 India is
    # "HMT", Howrah Mean Time, 19 degrees of longitude from Porbandar. That is
    # a 75-minute error, enough to move the ascendant nearly a whole sign.
    # Astrological practice uses the BIRTHPLACE'S own mean time for such dates.
    #
    # Detection: every genuine standard timezone is a whole multiple of 15
    # minutes (+1:00, +5:30, +5:45, +12:45). Local mean times are arbitrary,
    # because they derive from longitude. Anything not on a 15-minute boundary
    # is therefore a mean time, not a standard zone.
    #
    # Where this misfires -- the Netherlands' legally-standard +0:19:32, or
    # Liberia's -0:44:30 -- those offsets were themselves a city mean time
    # inside the same country, so substituting the birthplace's own mean time
    # is wrong by a minute or two rather than by the 75 minutes at stake when
    # a zone's reference city is genuinely far away. We record the override
    # either way so it is never invisible.
    iana_offset_hours = first.utcoffset().total_seconds() / 3600.0
    pre_standard_time = first.utcoffset().total_seconds() % 900 != 0

    if pre_standard_time:
        offset_hours = longitude / 15.0   # 15 degrees of longitude = 1 hour
        utc = (naive - timedelta(hours=offset_hours)).replace(tzinfo=timezone.utc)
        ambiguous = nonexistent = False   # no DST existed yet
    else:
        offset_hours = iana_offset_hours
        utc = first.astimezone(timezone.utc)

    import swisseph as swe
    jd = swe.julday(
        utc.year, utc.month, utc.day,
        utc.hour + utc.minute / 60.0 + utc.second / 3600.0,
    )

    return ResolvedMoment(
        local_input=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}",
        timezone_name=tzname,
        utc_offset_hours=offset_hours,
        iana_offset_hours=iana_offset_hours,
        used_local_mean_time=pre_standard_time,
        utc=utc,
        julian_day_ut=jd,
        ambiguous=ambiguous,
        nonexistent=nonexistent,
    )


# ------------------------------------------------------ clock times, for people
#
# The tools once handed out times in universal time and left the conversion to
# whoever read them. A conversion done in the head is a wrong hour sooner or
# later, and a wrong hour moves which day is recommended. So every clock time
# that leaves a tool goes through clock(), already in the time of the place
# the person is in.


def local(dt: datetime, tzname: str) -> datetime:
    """An instant as the clock on the wall reads it in that timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tzname))


def offset_label(dt: datetime, tzname: str) -> str:
    minutes = int(local(dt, tzname).utcoffset().total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def clock(dt: datetime, tzname: str, with_date: bool = True) -> str:
    """'2026-03-10 06:47 (UTC+01:00)': local clock time, with the offset that
    was applied on that date, so summer time is never guessed at."""
    at = local(dt, tzname)
    stamp = at.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M")
    return f"{stamp} ({offset_label(dt, tzname)})"


def instant(date_iso: str, hour: float, tzname: str) -> datetime:
    """The UTC instant of an hour on the clock, on a calendar date, there."""
    y, m, d = (int(x) for x in date_iso[:10].split("-"))
    naive = datetime(y, m, d) + timedelta(hours=hour)
    return naive.replace(tzinfo=ZoneInfo(tzname)).astimezone(timezone.utc)


def julian_day(dt: datetime) -> float:
    import swisseph as swe
    dt = dt.astimezone(timezone.utc)
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute / 60 + dt.second / 3600)


def locate(text: str) -> dict:
    """A place someone named, or coordinates they pasted, as a point on the
    earth with its timezone. Raises ValueError when it cannot be found."""
    from . import coords
    text = (text or "").strip()
    if not text:
        raise ValueError("no place given")
    try:
        c = coords.parse(text)
        return {"name": str(c), "latitude": c.latitude,
                "longitude": c.longitude,
                "timezone": timezone_for(c.latitude, c.longitude),
                "other_matches": []}
    except coords.CoordinateError:
        pass
    # "Lisbon, PT" or "Lisbon, Portugal": the part after the comma narrows it.
    city, _, rest = text.partition(",")
    hits = search_places(city.strip(), 25)
    want = rest.strip().lower()
    if want and hits:
        names = {c["iso"].lower(): c["name"].lower()
                 for c in _gc.get_countries().values()}
        narrowed = [h for h in hits if want in (h.country.lower(),
                                                names.get(h.country.lower(), ""))]
        hits = narrowed or hits
    if not hits:
        raise ValueError(
            f"no city called {text!r} in the built-in list. Try the nearest "
            "larger town, or paste coordinates from a map.")
    best = hits[0]
    return {"name": f"{best.name}, {best.country}", "latitude": best.latitude,
            "longitude": best.longitude,
            "timezone": timezone_for(best.latitude, best.longitude),
            "other_matches": [f"{h.name}, {h.country}" for h in hits[1:4]]}
