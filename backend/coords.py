"""Parsing coordinates in the shapes people actually paste.

Google Maps hands out several formats depending on where you copy from -- the
search box, a right-click, the URL, the place card -- and none of them agree.
Rather than telling you which one to use, accept all of them.

Coordinate precision matters less than it feels like it should: a hospital
rather than a city centre is about 0.05 degrees, which moves the ascendant by
roughly a tenth of a degree, or about 25 seconds of birth time. That is noise
against any birth time not already rectified. The real value is coverage --
villages and exact places that no city database contains.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Numbers, and the hemisphere letters, in the order they appear.
_TOKEN = re.compile(r"-?\d+(?:\.\d+)?|[NSEW]", re.IGNORECASE)


class CoordinateError(ValueError):
    """The text could not be read as a coordinate pair."""


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float

    def __str__(self) -> str:
        ns = "N" if self.latitude >= 0 else "S"
        ew = "E" if self.longitude >= 0 else "W"
        return f"{abs(self.latitude):.6f}{ns}, {abs(self.longitude):.6f}{ew}"


def _to_decimal(parts: list[float]) -> float:
    """Degrees, or degrees/minutes, or degrees/minutes/seconds."""
    if not parts or len(parts) > 3:
        raise CoordinateError(f"expected 1 to 3 numbers, got {len(parts)}")
    sign = -1.0 if parts[0] < 0 else 1.0
    value = abs(parts[0])
    if len(parts) > 1:
        value += parts[1] / 60.0
    if len(parts) > 2:
        value += parts[2] / 3600.0
    return sign * value


def _group(tokens: list[str]) -> list[tuple[list[float], str | None]]:
    """Split the token stream into two coordinates, however they are written.

    Hemisphere letters may trail their numbers (44 47 11 N) or lead them
    (N 44.7866). Both appear in the wild.
    """
    groups: list[tuple[list[float], str | None]] = []
    numbers: list[float] = []
    leading: str | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in "NSEW":
            if numbers:
                groups.append((numbers, token))
                numbers = []
            else:
                leading = token
            i += 1
            continue
        numbers.append(float(token))
        i += 1
        # With a leading hemisphere, the group closes at the next letter or end.
        if leading is not None and (i >= len(tokens) or tokens[i] in "NSEW"):
            groups.append((numbers, leading))
            numbers, leading = [], None
    if numbers:
        groups.append((numbers, leading))
    return groups


def parse(text: str) -> Coordinates:
    """Read a coordinate pair from free text.

    Accepts, among others:
        44.7866, 20.4489
        44.7866 20.4489
        44 deg 47' 11.8" N  20 deg 26' 56.0" E
        N44.7866 E20.4489
        -33.8688, 151.2093
    """
    if not text or not text.strip():
        raise CoordinateError("nothing to parse")

    tokens = [t.upper() for t in _TOKEN.findall(text)]
    if not tokens:
        raise CoordinateError(f"no numbers found in {text!r}")

    groups = _group(tokens)

    # No hemisphere letters at all: one run of numbers, split down the middle.
    if len(groups) == 1 and groups[0][1] is None:
        numbers = groups[0][0]
        if len(numbers) % 2 != 0:
            raise CoordinateError(
                f"expected an even count of numbers, got {len(numbers)}")
        half = len(numbers) // 2
        groups = [(numbers[:half], None), (numbers[half:], None)]

    if len(groups) != 2:
        raise CoordinateError(f"expected two coordinates, found {len(groups)}")

    values, hemispheres = [], []
    for numbers, hemisphere in groups:
        value = _to_decimal(numbers)
        if hemisphere in ("S", "W"):
            value = -abs(value)
        elif hemisphere in ("N", "E"):
            value = abs(value)
        values.append(value)
        hemispheres.append(hemisphere)

    # Hemispheres name the axes; without them, latitude comes first by convention.
    if hemispheres[0] in ("E", "W") or hemispheres[1] in ("N", "S"):
        latitude, longitude = values[1], values[0]
    else:
        latitude, longitude = values[0], values[1]

    if not -90.0 <= latitude <= 90.0:
        raise CoordinateError(f"latitude {latitude} is outside -90 to 90")
    if not -180.0 <= longitude <= 180.0:
        raise CoordinateError(f"longitude {longitude} is outside -180 to 180")
    return Coordinates(latitude=latitude, longitude=longitude)
