"""Draws extension/icon.png and docs/icon.png: a north-Indian chart outline.

Run it only to change the icon; the PNGs are committed.
    python extension/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 8                      # drawn large, then scaled down, for smooth edges
N = 256 * S
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, N - 1, N - 1], radius=52 * S, fill="#3b2463")
a, b, mid = 44 * S, N - 44 * S, N // 2
gold, w = "#e9c46a", 7 * S
d.rectangle([a, a, b, b], outline=gold, width=w)
d.line([a, a, b, b], fill=gold, width=w)
d.line([a, b, b, a], fill=gold, width=w)
d.polygon([(mid, a), (b, mid), (mid, b), (a, mid)], outline=gold, width=w)
r = 13 * S
d.ellipse([mid - r, mid - 52 * S - r, mid + r, mid - 52 * S + r], fill="#f6f1e4")
out = img.resize((512, 512), Image.LANCZOS)
root = Path(__file__).resolve().parent.parent
for target in (root / "extension" / "icon.png", root / "docs" / "icon.png"):
    target.parent.mkdir(exist_ok=True)
    out.save(target, optimize=True)
    print(target)
