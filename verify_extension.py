"""Checks on the Claude Desktop extension, without building it.

The built program is tried for real by tools/build_extension.py on each
operating system. This suite guards what can drift in between: the manifest,
the server it describes, the first-run folder and the download page.
"""
import sys
sys.path.insert(0, ".")

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

results = []


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


ROOT = Path(__file__).parent.resolve()
scratch = Path(tempfile.mkdtemp())
home = scratch / "not" / "there" / "yet"
os.environ["JYOTISHA_HOME"] = str(home)
os.environ.pop("JYOTISHA_DB", None)

from backend import extension, mcp_server, paths  # noqa: E402

manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))

print("=" * 72)
print("1. The data folder on first run")
check("the folder comes from the extension's setting", paths.data_dir() == home)
extension.first_run()
note = home / extension.ABOUT_NAME
check("it is created, with a note saying what it is",
      note.exists() and "jyotisha.db" in note.read_text(encoding="utf-8"))
note.write_text("mine", encoding="utf-8")
extension.first_run()
check("a second start leaves the folder as it was",
      note.read_text(encoding="utf-8") == "mine")
os.environ["JYOTISHA_HOME"] = "${user_config.data_folder}"
os.environ["JYOTISHA_BACKUPS"] = "${user_config.backup_folder}"
check("a setting that was never filled in falls back to the default",
      paths.data_dir() == paths.DEFAULT_DATA
      and paths._env("JYOTISHA_BACKUPS") is None)
os.environ["JYOTISHA_HOME"] = str(home)
os.environ["JYOTISHA_BACKUPS"] = str(scratch / "backups")
check("the backup folder comes from the extension's setting",
      paths.backup_dir() == scratch / "backups")
(home / "settings.json").write_text(
    json.dumps({"backup_folder": str(scratch / "chosen")}), encoding="utf-8")
check("unless settings.json in the data folder names one",
      paths.backup_dir() == scratch / "chosen")
blocked = scratch / "a-file"
blocked.write_text("x")
os.environ["JYOTISHA_HOME"] = str(blocked / "under")
try:
    extension.first_run()
    check("a folder that cannot be created does not stop the server", True)
except Exception as exc:
    check("a folder that cannot be created does not stop the server", False, str(exc))
os.environ["JYOTISHA_HOME"] = str(home)

print()
print("=" * 72)
print("2. The server the extension runs")
server = extension.build()
offered = sorted(t.name for t in asyncio.run(server.list_tools()))
expected = sorted([f.__name__ for f in mcp_server.TOOLS + mcp_server.LOCAL_TOOLS]
                  + ["guidance"])
check("every local tool is offered, plus guidance", offered == expected,
      f"{len(offered)} tools")
prompts = sorted(p.name for p in asyncio.run(server.list_prompts()))
check("onboard, ask and journal are offered as prompts",
      prompts == ["ask", "journal", "onboard"])
ins = server.instructions
check("the instructions open by pointing a newcomer at the guidance",
      ins.startswith("START HERE") and "onboard" in ins[:900])
check("and carry the advisor's voice from SYSTEM_RULES",
      "never calculate" in ins.lower())
check("they say where the data is kept and how to back it up",
      "own computer" in ins and "back_up_data" in ins)
check("they cover correcting and removing a profile",
      "correct_profile" in ins and "remove_profile" in ins and "confirm_name" in ins)

print()
print("=" * 72)
print("3. The manifest describes that server")
listed = sorted(t["name"] for t in manifest["tools"])
check("it lists exactly the tools offered", listed == offered,
      f"differ: {sorted(set(listed) ^ set(offered))}")
check("each with a description", all(t.get("description") for t in manifest["tools"]))
check("the version is three numbers, as the release tag needs",
      re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]), manifest["version"])
env = manifest["server"]["mcp_config"]["env"]
check("both folders are settings the person can change",
      env == {"JYOTISHA_HOME": "${user_config.data_folder}",
              "JYOTISHA_BACKUPS": "${user_config.backup_folder}"}
      and all(manifest["user_config"][k]["type"] == "directory"
              for k in ("data_folder", "backup_folder")))
# Claude Desktop leaves an extension switched off after installing, and its
# Save button grey, while a required setting is empty -- and a default does
# not count as filled in. Nothing may be required, so it installs and runs
# with no choices made; the folders then come from paths.py.
check("nothing has to be filled in before it works",
      not any(v.get("required") for v in manifest["user_config"].values()))
check("no folder is suggested as text the person would have to make sense of",
      not any("default" in v for v in manifest["user_config"].values()))
check("the icon it names is there", (ROOT / "extension" / manifest["icon"]).exists())
check("no API key or network service is asked for",
      not any(v.get("sensitive") for v in manifest["user_config"].values())
      and "privacy_policies" not in manifest)

print()
print("=" * 72)
print("4. The download page and the release agree on the file names")
page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
builder = (ROOT / "tools" / "build_extension.py").read_text(encoding="utf-8")
for label in ("windows", "mac-apple-silicon", "mac-intel"):
    name = f"zeljko-{label}.mcpb"
    check(f"{name} is linked from the page as the latest release",
          f"releases/latest/download/{name}" in page and f'"{label}"' in builder)
check("the release is tagged from the manifest's version",
      "extension/manifest.json" in workflow)
check("the page links to the source, as the licence asks",
      "https://github.com/nidzus/zeljko" in page)

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
