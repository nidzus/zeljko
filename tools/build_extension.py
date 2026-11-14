"""Build the Claude Desktop extension (.mcpb) for the computer this runs on.

    python jyotisha.py extension          (or "Build extension")

It freezes backend/extension.py and everything it needs into one program with
PyInstaller, so the person installing it needs no Python; packs it with
extension/manifest.json; then opens the packed file again, starts the program
inside and talks to it the way Claude Desktop will, against an empty scratch
data folder. A file that fails that is deleted. The result is one of

    dist/zeljko-windows.mcpb
    dist/zeljko-mac-apple-silicon.mcpb
    dist/zeljko-mac-intel.mcpb

A frozen program only runs on the kind of computer it was built on, so each
file is built on its own system. .github/workflows/release.yml does all three
and publishes them; this script is the same thing by hand, for trying a
change. Needs the project's Python plus requirements-build.txt, and Node.js
for the packer.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "build" / "extension"
DIST = ROOT / "dist"
PACKER = "@anthropic-ai/mcpb@2.1.2"
WINDOWS = sys.platform == "win32"


def target() -> tuple[str, str]:
    """(file label, manifest platform) for this computer."""
    if WINDOWS:
        return "windows", "win32"
    if sys.platform == "darwin":
        arm = platform.machine().lower() in ("arm64", "aarch64")
        return ("mac-apple-silicon" if arm else "mac-intel"), "darwin"
    raise SystemExit("The extension is built for Windows and macOS only.")


def run(cmd: list, **kw) -> None:
    print(">", " ".join(str(c) for c in cmd[:6]), "..." if len(cmd) > 6 else "")
    sys.stdout.flush()
    if subprocess.run([str(c) for c in cmd], cwd=ROOT, **kw).returncode != 0:
        raise SystemExit(f"\nFAILED: {cmd[0]} did not finish. The reason is above.")


def freeze() -> Path:
    """The frozen program, as a folder: zeljko(.exe) beside _internal/."""
    sep = os.pathsep
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--onedir", "--console", "--name", "zeljko",
         "--distpath", WORK / "frozen", "--workpath", WORK / "work",
         "--specpath", WORK,
         # Files the code reads from beside itself (store.py, guidance.py).
         "--add-data", f"{ROOT / 'backend' / 'schema.sql'}{sep}backend",
         "--add-data", f"{ROOT / 'jyotisha-plugin' / 'skills'}{sep}jyotisha-plugin/skills",
         # Data carried inside packages: timezone shapes, cities, tz rules.
         "--collect-data", "timezonefinder", "--collect-data", "geonamescache",
         "--collect-data", "tzdata",
         # Imported by name at run time, which the freezer cannot see.
         "--collect-submodules", "mcp", "--hidden-import", "backend.backup",
         # Present in the environment, never used by the advisor's tools.
         "--exclude-module", "reportlab", "--exclude-module", "pypdf",
         "--exclude-module", "tkinter",
         ROOT / "extension" / "launch.py"])
    return WORK / "frozen" / "zeljko"


def stage(frozen: Path, platform_key: str) -> Path:
    staged = WORK / "bundle"
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    shutil.copytree(frozen, staged / "server", symlinks=True)
    # The city package ships four lists; timeplace.py uses its default, the
    # places of 15,000 people and over. The other three are 160 MB unread.
    for unused in (staged / "server").rglob("geonamescache/**/cities*.json"):
        if unused.name != "cities15000.json":
            unused.unlink()
    shutil.copy2(ROOT / "extension" / "icon.png", staged / "icon.png")
    shutil.copy2(ROOT / "LICENSE", staged / "LICENSE")
    shutil.copy2(ROOT / "NOTICE.md", staged / "NOTICE.md")
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    exe = "server/zeljko.exe" if WINDOWS else "server/zeljko"
    manifest["server"]["entry_point"] = exe
    manifest["server"]["mcp_config"]["command"] = "${__dirname}/" + exe
    manifest["compatibility"]["platforms"] = [platform_key]
    (staged / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return staged


class Session:
    """The frozen program, spoken to as Claude Desktop speaks to it."""

    def __init__(self, exe: Path, home: Path, backups: Path):
        env = {**os.environ, "JYOTISHA_HOME": str(home),
               "JYOTISHA_BACKUPS": str(backups)}
        for name in ("JYOTISHA_DB", "PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        self.proc = subprocess.Popen(
            [str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=tempfile.gettempdir(), text=True,
            encoding="utf-8", bufsize=1)
        self.stderr: list[str] = []
        threading.Thread(target=lambda: self.stderr.extend(self.proc.stderr),
                         daemon=True).start()
        self.n = 0

    def ask(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n,
                                          "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise SystemExit("FAILED: the program stopped. It said:\n"
                                 + "".join(self.stderr)[-3000:])
            if line.lstrip().startswith("{"):
                reply = json.loads(line)
                if reply.get("id") == self.n:
                    return reply

    def tell(self, method: str) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                          "params": {}}) + "\n")
        self.proc.stdin.flush()

    def call(self, tool: str, /, **arguments) -> tuple[str, bool]:
        result = self.ask("tools/call", {"name": tool, "arguments": arguments})["result"]
        text = "".join(c.get("text", "") for c in result["content"])
        return text, bool(result.get("isError"))

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def try_it(staged: Path) -> None:
    """A first run, start to finish, with a made-up person."""
    manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
    exe = staged / manifest["server"]["entry_point"]
    scratch = Path(tempfile.mkdtemp())
    home, backups = scratch / "new" / "data folder", scratch / "backups"
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    s = Session(exe, home, backups)
    try:
        init = s.ask("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "build-check", "version": "1"}})
        ins = init["result"].get("instructions", "")
        check("it starts and introduces itself",
              ins.startswith("START HERE") and "never calculate" in ins.lower())
        s.tell("notifications/initialized")
        check("the data folder was created on first run, with its note",
              any(home.glob("About*.txt")))
        offered = {t["name"] for t in s.ask("tools/list")["result"]["tools"]}
        listed = {t["name"] for t in manifest["tools"]}
        check("it offers exactly the tools the manifest lists", offered == listed,
              f"differ: {sorted(offered ^ listed)}")
        prompts = {p["name"] for p in s.ask("prompts/list")["result"]["prompts"]}
        check("onboard, ask and journal are offered as prompts",
              prompts == {"onboard", "ask", "journal"})
        text, err = s.call("guidance", topic="onboard")
        check("the onboarding guidance is inside the program",
              not err and "How well that time is known" in text)
        text, err = s.call("list_people")
        check("a new person starts with no profiles", not err and "person_id" not in text)
        text, err = s.call("search_places", query="Belgrade")
        check("the city database is inside the program", not err and "Belgrade" in text)
        text, err = s.call("create_profile", name="Build Check", birth_date="1988-03-12",
                           birth_time="16:30", place_name="Belgrade, RS",
                           latitude=44.7866, longitude=20.4489,
                           time_confidence="REMEMBERED")
        check("a profile is created: ephemeris and timezone data work",
              not err and "Europe/Belgrade" in text and "lagna" in text, text[:200])
        check("the database is in the chosen data folder", (home / "jyotisha.db").exists())
        text, err = s.call("dasha_at", date="2026-11-15")
        check("periods are computed", not err and "periods" in text, text[:200])
        text, err = s.call("personal_day", date="2026-11-15")
        check("the day-scale tools work", not err, text[:200])
        text, err = s.call("correct_profile", note="build check", birth_time="16:45")
        check("a correction is stored, after a safety copy",
              not err and "previous_version_kept" in text
              and any((home / "archive").glob("*correct-profile*")), text[:200])
        text, err = s.call("back_up_data")
        check("a backup lands in the backup folder",
              not err and any(backups.glob("jyotisha-*.db")), text[:200])
        text, err = s.call("remove_profile", person_id="Build Check",
                           confirm_name="Build Check")
        check("a profile is removed once confirmed", not err and '"deleted": true' in text.lower(),
              text[:200])
    finally:
        s.close()
        shutil.rmtree(scratch, ignore_errors=True)
    if failures:
        raise SystemExit(f"\nFAILED: the built extension did not pass: {failures}\n"
                         + "".join(s.stderr)[-3000:])


def pack(staged: Path, label: str) -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"zeljko-{label}.mcpb"
    out.unlink(missing_ok=True)
    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("FAILED: Node.js is needed to pack the extension "
                         "(https://nodejs.org). Everything before this step passed.")
    run([npx, "--yes", PACKER, "pack", staged, out])
    return out


def unpack(packed: Path) -> Path:
    """The packed file opened again, as installing it does -- so what is
    tried is what was shipped, with whatever packing did to it."""
    opened = WORK / "unpacked"
    shutil.rmtree(opened, ignore_errors=True)
    run([shutil.which("npx"), "--yes", PACKER, "unpack", packed, opened])
    return opened


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("PyInstaller is missing. Run:  python jyotisha.py extension")
    label, platform_key = target()
    version = json.loads((ROOT / "extension" / "manifest.json")
                         .read_text(encoding="utf-8"))["version"]
    print(f"Building Zeljko {version} for {label}\n")
    frozen = WORK / "frozen" / "zeljko"
    if "--reuse" not in sys.argv or not frozen.exists():   # --reuse: skip the slow step
        frozen = freeze()
    staged = stage(frozen, platform_key)
    out = pack(staged, label)
    print("\nOpening the packed file and trying it as Claude Desktop would\n")
    try:
        try_it(unpack(out))
    except SystemExit:
        out.unlink(missing_ok=True)      # never leave a file that failed
        raise
    print(f"\nBuilt: {out}  ({out.stat().st_size / 1e6:.0f} MB)")
    print("To try it, double-click that file, or drag it onto Claude Desktop's")
    print("Settings > Extensions page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
