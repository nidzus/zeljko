"""Derive Plain and Full editions from a reading template, print each to PDF
with headless Chrome, and verify the PDFs with pypdf.

    python tools/build_reading.py <subject>

Templates are personal, so they live in the data folder, not here:
<data>/readings/source/<subject>-template.html. The PDFs are written to
<data>/readings/. The person a reading is about is taken from the start of
the template's <title>, and the check confirms that name is in the PDF.
"""
import html as htmllib, os, re, shutil, subprocess, sys, pathlib
from pypdf import PdfReader

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from backend import paths  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)
OUT_DIR = paths.data_dir() / "readings"
HERE = OUT_DIR / "source"
PROFILE = HERE / "chrome-profile"
SUBJECT = sys.argv[1]
TITLE = SUBJECT.capitalize()
template = HERE / f"{SUBJECT}-template.html"
if not template.exists():
    sys.exit(f"No template at {template}")
tpl = template.read_text(encoding="utf-8")


def chrome() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for name in ("google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("Google Chrome was not found; it prints the PDFs.")


CHROME = chrome()

TECH = re.compile(r"<!--TECH-->.*?<!--/TECH-->", re.S)
if SUBJECT == "scenarios":
    editions = {"Working": tpl.replace("<!--TECH-->", "").replace("<!--/TECH-->", "")
                              .replace("{{EDITION}}", "Working")}
else:
    editions = {
        "Plain": TECH.sub("", tpl).replace("{{EDITION}}", "Plain"),
        "Full":  tpl.replace("<!--TECH-->", "").replace("<!--/TECH-->", "").replace("{{EDITION}}", "Full"),
    }

# "Name — Natal Reading (...)" or "Name & Name — ..." -> the first name.
title = re.search(r"<title>(.*?)</title>", tpl, re.S)
first = re.split(r"[\s—&;,-]+", htmllib.unescape(title.group(1)).strip())[0] if title else ""
subject_needle = (first or TITLE).lower()

results = []
for name, html in editions.items():
    src = HERE / f"{SUBJECT}-{name.lower()}.html"
    out = OUT_DIR / f"{TITLE}-Natal-Reading-{name}.pdf"
    src.write_text(html, encoding="utf-8")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           f"--user-data-dir={PROFILE}", "--no-pdf-header-footer",
           "--virtual-time-budget=8000", "--run-all-compositor-stages-before-draw",
           f"--print-to-pdf={out}", src.as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
    if not out.exists():
        print(f"[{name}] FAILED — no PDF produced\nstderr tail:\n{r.stderr[-1500:]}")
        sys.exit(1)
    reader = PdfReader(str(out))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    results.append((name, out, len(reader.pages), out.stat().st_size, text, html))

print(f"{'edition':<7} {'pages':>5} {'bytes':>9}  checks")
for name, out, pages, size, text, html in results:
    # PDF extraction wraps lines mid-phrase and CSS uppercases section labels,
    # so compare case-insensitively with whitespace collapsed.
    low = ' '.join(text.lower().split())
    checks = []
    checks.append(("edition label", f"{name} edition".lower() in low))
    # Structural, not textual: the word "technical" also occurs in body prose.
    panels = html.count('class="tech"')
    if SUBJECT != "scenarios":
        checks.append(("tech panels", (panels > 0) == (name == "Full")))
    if SUBJECT != "scenarios":
        checks.append(("closing section", "would change this" in low))
    if SUBJECT != "scenarios":
        checks.append(("glossary", "glossary" in low or name != "Full"))
    else:
        checks.append(("recommendation", "standing recommendation" in low))
    if SUBJECT != "scenarios":
        checks.append(("chart caption", "compartment" in low))
    checks.append(("subject named", subject_needle in low))
    ok = all(v for _, v in checks)
    flags = ", ".join(f"{k}:{'ok' if v else 'FAIL'}" for k, v in checks)
    print(f"{name:<7} {pages:>5} {size:>9}  {flags}  tech-panels={panels}")
    if not ok:
        sys.exit(2)
print("\nfiles:")
for name, out, *_rest in results:
    print("  ", out)
