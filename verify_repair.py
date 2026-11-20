"""Checks on tools/repair_paths.py, on made-up config files in a scratch folder.

The real config files belong to the machine, so nothing here reads or writes
them: every file is created in a temporary folder first.
"""
import sys
sys.path.insert(0, ".")

import json
import tempfile
from pathlib import Path

from tools import repair_paths as rp

results = []


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


scratch = Path(tempfile.mkdtemp())
want = rp.wanted()


def write(path: Path, servers: dict, **extra) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers, **extra}), encoding="utf-8")
    return path


def servers(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"]


old_entry = {"command": "C:/old/place/python.exe", "args": ["-m", "backend.mcp_server"],
             "env": {"PYTHONPATH": "C:/old/place", "JYOTISHA_DB": "C:/old/data/jyotisha.db"}}
other = {"command": "npx", "args": ["some-other-server"]}

print("=" * 72)
print("1. The server is called zeljko")
check("the entry name is zeljko", rp.SERVER == "zeljko")
check("its paths are this app's", want["env"]["PYTHONPATH"] == str(rp.ROOT)
      and want["args"] == ["-m", "backend.mcp_server"])

print("=" * 72)
print("2. An entry under the old name is renamed, not duplicated")
cfg = write(scratch / "desk" / "claude_desktop_config.json",
            {"jyotisha": old_entry, "other": other}, preferences={"keep": 1})
status = rp.patch(cfg, "test", create=False, add=False, backup=True)
s = servers(cfg)
check("the file is changed", status == "changed")
check("the old name is gone", "jyotisha" not in s, sorted(s))
check("the new entry points at these folders",
      s.get("zeljko", {}).get("command") == want["command"]
      and s["zeljko"]["env"] == want["env"])
check("other servers and settings are kept",
      s.get("other") == other
      and json.loads(cfg.read_text(encoding="utf-8"))["preferences"] == {"keep": 1})
check("a backup was taken first",
      any(p.name.startswith("claude_desktop_config.json.bak-") for p in cfg.parent.iterdir()))
check("a second run changes nothing",
      rp.patch(cfg, "test", create=False, add=False, backup=True) == "unchanged")

print("=" * 72)
print("3. Both names present: the old one goes, the new one is corrected")
cfg = write(scratch / "both.json", {"jyotisha": old_entry, "zeljko": old_entry})
rp.patch(cfg, "test", create=False, add=False, backup=False)
s = servers(cfg)
check("only zeljko is left", sorted(s) == ["zeljko"], sorted(s))
check("and it is correct", s["zeljko"]["env"] == want["env"])

print("=" * 72)
print("4. A different server that happens to be called jyotisha is left alone")
foreign = {"command": "node", "args": ["someone-elses-astrology.js"]}
cfg = write(scratch / "foreign.json", {"jyotisha": foreign})
status = rp.patch(cfg, "test", create=False, add=False, backup=False)
check("nothing is changed", status == "absent" and servers(cfg) == {"jyotisha": foreign})

print("=" * 72)
print("5. The installed plugin copy")
skills = scratch / "skills"
write(skills / "jyotisha" / ".mcp.json", {"jyotisha": old_entry})
(skills / "jyotisha" / ".claude-plugin").mkdir(parents=True)
(skills / "jyotisha" / ".claude-plugin" / "plugin.json").write_text(
    '{"name": "jyotisha"}', encoding="utf-8")
statuses = rp.installed_plugin(skills)
target = skills / "zeljko"
check("an old copy is moved to the new name", target.is_dir()
      and not (skills / "jyotisha").exists())
check("its plugin name is refreshed from the app",
      json.loads((target / ".claude-plugin" / "plugin.json").read_text(
          encoding="utf-8"))["name"] == "zeljko")
check("its skills are there", all((target / "skills" / t / "SKILL.md").exists()
                                  for t in ("ask", "journal", "onboard")))
check("its .mcp.json names zeljko, pointing here",
      sorted(servers(target / ".mcp.json")) == ["zeljko"]
      and servers(target / ".mcp.json")["zeljko"]["env"] == want["env"])
check("a second run changes nothing",
      "changed" not in rp.installed_plugin(skills))
(skills / "jyotisha").mkdir()
rp.installed_plugin(skills)
check("a leftover old copy beside the new one is not deleted",
      (skills / "jyotisha").is_dir())
check("with no copy installed, nothing is created",
      rp.installed_plugin(scratch / "empty") == ["absent"]
      and not (scratch / "empty").exists())

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
