"""Drawing a chart, as support rather than as the answer.

North Indian layout: the houses hold fixed positions and the signs move between
them. That is the right choice here because the reading is house-shaped -- the
10th is always the same box on the page, so "the part that governs work" ends
up with a stable place to point at.

The transit view puts today's grahas into the natal houses, which is what
gochara means in practice: not where the sky is, but where the sky is relative
to you.

The SVG carries its own styling so it works standalone, in light and dark.
"""
from __future__ import annotations

import swisseph as swe

from . import ephemeris, transits

SHORT = {"Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me",
         "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa", "Rahu": "Ra",
         "Ketu": "Ke"}

# Fractions of the square. Houses run counter-clockwise from the top centre.
ANCHORS = [
    (0.50, 0.25), (0.25, 0.10), (0.10, 0.25), (0.25, 0.50),
    (0.10, 0.75), (0.25, 0.90), (0.50, 0.75), (0.75, 0.90),
    (0.90, 0.75), (0.75, 0.50), (0.90, 0.25), (0.75, 0.10),
]

STYLE = """
.f{fill:none;stroke:#b9b2a4;stroke-width:1}
.s{fill:#9b9283;font:10px ui-monospace,monospace}
.n{fill:#1f1d1a;font:13px system-ui,sans-serif}
.l{fill:#8a5a1f;font:13px system-ui,sans-serif;font-weight:500}
.t{fill:#1d6f8a;font:12px system-ui,sans-serif}
.c{fill:#6b665d;font:11px system-ui,sans-serif}
.h{fill:#f0ece2;stroke:none}
@media (prefers-color-scheme:dark){
.f{stroke:#4a4638}.s{fill:#78735f}.n{fill:#ece8df}.l{fill:#d3b075}
.t{fill:#7fc4dd}.c{fill:#a8a294}.h{fill:#2b2517}}
"""


def _cell_lines(names: list[str], per_row: int = 2) -> list[str]:
    return [" ".join(names[i:i + per_row]) for i in range(0, len(names), per_row)]


def north_indian(chart: ephemeris.Chart, transit_date: str | None = None,
                 caption: str = "", highlight: list[int] | None = None,
                 size: int = 360) -> str:
    """Render the chart, optionally with today's grahas laid over it."""
    S = size
    half, pad = S / 2, 30
    highlight = highlight or []

    natal: dict[int, list[str]] = {}
    for p in chart.positions:
        natal.setdefault(p.house, []).append(
            SHORT[p.name] + ("ʳ" if p.retrograde and p.name
                             not in ("Rahu", "Ketu") else ""))

    moving: dict[int, list[str]] = {}
    if transit_date:
        y, m, d = (int(x) for x in transit_date.split("-"))
        jd = swe.julday(y, m, d, 12.0)
        for name in list(SHORT):
            longitude, speed = transits.state(jd, name, chart.ayanamsa_name)
            house = chart.house_of(int(longitude // 30))
            moving.setdefault(house, []).append(
                SHORT[name] + ("ʳ" if speed < 0 and name
                               not in ("Rahu", "Ketu") else ""))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} '
             f'{S + pad + (18 if caption else 0)}" width="{S}" role="img">',
             f"<style>{STYLE}</style>",
             f"<title>{caption or 'Chart'}</title>"]

    for house in highlight:
        i = house - 1
        fx, fy = ANCHORS[i]
        parts.append(f'<circle class="h" cx="{fx * S:.0f}" cy="{fy * S:.0f}" '
                     f'r="{S * 0.085:.0f}"/>')

    parts += [
        f'<rect class="f" x="0.5" y="0.5" width="{S - 1}" height="{S - 1}"/>',
        f'<path class="f" d="M0 0 L{S} {S} M{S} 0 L0 {S}"/>',
        f'<path class="f" d="M{half} 0 L{S} {half} L{half} {S} L0 {half} Z"/>',
    ]

    for i, (fx, fy) in enumerate(ANCHORS):
        house = i + 1
        x, y = fx * S, fy * S
        sign = chart.sign_in_house(house)
        parts.append(f'<text class="s" x="{x:.0f}" y="{y - 16:.0f}" '
                     f'text-anchor="middle">{sign + 1}</text>')

        rows = natal.get(house, [])
        if house == 1:
            rows = ["As"] + rows
        for r, line in enumerate(_cell_lines(rows)):
            cls = "l" if house == 1 and r == 0 else "n"
            parts.append(f'<text class="{cls}" x="{x:.0f}" '
                         f'y="{y - 2 + r * 14:.0f}" text-anchor="middle">'
                         f'{line}</text>')

        if house in moving:
            base = y - 2 + len(_cell_lines(rows)) * 14
            for r, line in enumerate(_cell_lines(moving[house])):
                parts.append(f'<text class="t" x="{x:.0f}" '
                             f'y="{base + r * 13:.0f}" text-anchor="middle">'
                             f'{line}</text>')

    legend = "natal in dark" + (", transiting in blue" if transit_date else "")
    parts.append(f'<text class="c" x="0" y="{S + 16}">{legend}. '
                 f'Superscript r marks retrograde.</text>')
    if caption:
        parts.append(f'<text class="c" x="0" y="{S + 32}">{caption}</text>')
    parts.append("</svg>")
    return "".join(parts)
