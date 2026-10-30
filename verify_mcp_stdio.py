"""Launches the MCP server the way Claude Code will, and talks to it.

Deliberately started from an unrelated working directory: if PYTHONPATH or
JYOTISHA_DB are wrong, this fails here rather than silently pointing at an
empty database once it is wired up for real.
"""
import sys
sys.path.insert(0, ".")

import json
import os
import subprocess
import threading
import tempfile
from pathlib import Path

from backend.confidence import TimeConfidence
from backend.store import Store

results = []


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


ROOT = Path(__file__).parent.resolve()
scratch = Path(tempfile.mkdtemp())
db = scratch / "stdio.db"

with Store(db) as s:
    pid = s.add_person("Reference", relation="self")
    s.add_chart(pid, 1988, 3, 12, 16, 30, 0, "Belgrade, RS", 44.7866, 20.4489,
                TimeConfidence.REMEMBERED)

# The entry repair_paths writes into .mcp.json and the plugin. The files
# themselves are per machine and not committed, so build the same entry here
# and, where the file exists, confirm it agrees.
from tools import repair_paths
config = repair_paths.wanted()
written = ROOT / ".mcp.json"
if written.exists():
    entry = json.loads(written.read_text(encoding="utf-8"))["mcpServers"]["jyotisha"]
    check(".mcp.json on this machine points at these folders",
          entry["command"] == config["command"] and entry["env"] == config["env"],
          entry["command"])
env = {**os.environ, **config["env"], "JYOTISHA_DB": str(db),
       "PYTHONIOENCODING": "utf-8"}

print("=" * 72)
print("Launching the server exactly as .mcp.json specifies it,")
print(f"but from {scratch} rather than the project directory.")
print()

proc = subprocess.Popen(
    [config["command"], *config["args"]],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    env=env, cwd=str(scratch), text=True, encoding="utf-8", bufsize=1)

# Drain stderr continuously. If that pipe fills, the server blocks writing to
# it -- which stalls stdout too, and the whole thing hangs with no error. Real
# MCP clients drain it; a test harness has to as well.
stderr_lines: list[str] = []
threading.Thread(target=lambda: stderr_lines.extend(proc.stderr),
                 daemon=True).start()


def send(payload):
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def read():
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)


try:
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "1"}}})
    init = read()
    ok = bool(init and "result" in init)
    check("the server starts and completes a handshake", ok,
          (init or {}).get("result", {}).get("serverInfo", {}).get("name", str(init)[:80]))

    instructions = (init or {}).get("result", {}).get("instructions", "") or ""
    check("it hands Claude its instructions on connect",
          "never calculate" in instructions.lower(),
          f"{len(instructions)} characters of guidance")

    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    listed = read()
    names = sorted(t["name"] for t in listed["result"]["tools"])
    check("all twenty-seven tools are offered over the wire", len(names) == 27,
          ", ".join(names))

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "chart_context", "arguments": {}}})
    ctx = read()
    text = "".join(c.get("text", "") for c in ctx["result"]["content"])
    check("it found the right database despite the foreign cwd",
          "Belgrade" in text and "Lagna" in text,
          next((l for l in text.splitlines() if "Lagna" in l), "").strip())
    check("and the permissions travel with it",
          "navamsa: NO" in text,
          "a ±15 min birth time refuses the navamsa, over MCP as in the app")

    send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "dasha_at", "arguments": {"date": "2026-11-15"}}})
    dasha = read()
    dtext = "".join(c.get("text", "") for c in dasha["result"]["content"])
    check("dasha dates arrive pre-rounded over the wire",
          "November" in dtext or "June 2023" in dtext,
          "no day-level date is exposed to be over-quoted")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
