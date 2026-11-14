"""The advisor as a Claude Desktop extension (.mcpb).

The same tools as backend/mcp_server.py, run on the person's own computer
against their own database, for someone who has installed nothing else: no
Python, no git, no plugin. So this entry point adds what the plugin and the
installer would otherwise have provided:

- the data folder is created on first run, with a note saying what it is;
- the onboarding, ask and journal guidance is served by the server itself,
  from the same three skill files, as the `guidance` tool and as prompts.

tools/build_extension.py freezes this into one program per operating system
and packs it with extension/manifest.json. The data folder comes from the
extension's settings, passed in as JYOTISHA_HOME (see backend/paths.py).
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import guidance, mcp_server, paths

INSTRUCTIONS = """START HERE

The person installed this as a Claude Desktop extension and has nothing else
set up, so the working guidance comes from the guidance tool. Assume no
technical background: never ask them to run a command or edit a file.

Call list_people first. If it comes back empty they are new: say in a
sentence or two what this is (a jyotisha advisor that answers questions about
decisions from their computed chart, and keeps a journal of what was advised
and how it turned out), then call guidance with topic "onboard" and follow it.
Before advising on a decision call guidance with topic "ask"; before reviewing
past advice, topic "journal". Once per conversation each.

Everything they tell you is stored on their own computer, in the data folder
named in the extension's settings, and nowhere else. If they ask where their
data is or how to keep it safe, tell them that, and offer back_up_data.

""" + mcp_server.INSTRUCTIONS

ABOUT = """\
Zeljko, the jyotisha advisor: your data folder
==============================================

Everything the advisor knows about you is in this folder, on this computer.
Nothing here is sent anywhere by the extension.

  jyotisha.db   your profiles, charts, life events and decision journal
  archive       copies taken automatically before a profile is corrected
                or removed, so a mistake can be undone

To make a backup, ask Claude: "back up my data". The copy goes to the backup
folder chosen in the extension's settings.

To move to a new computer, install the extension there and copy this whole
folder across to the same place.

Do not rename or edit jyotisha.db while Claude is open.

More: https://github.com/nidzus/zeljko
"""
ABOUT_NAME = "About this folder.txt"


def first_run() -> None:
    """Create the data folder if this is the first start. The database itself
    appears when the first tool is called."""
    data = paths.data_dir()
    try:
        data.mkdir(parents=True, exist_ok=True)
        note = data / ABOUT_NAME
        if not note.exists():
            note.write_text(ABOUT, encoding="utf-8")
    except OSError:
        # Not fatal here: the first tool call reports it in words Claude can
        # pass on (see mcp_server._get_store).
        pass


def build() -> MCPServer:
    server = MCPServer(name="zeljko", title="Zeljko, the jyotisha advisor",
                       instructions=INSTRUCTIONS)
    for fn in mcp_server.TOOLS + mcp_server.LOCAL_TOOLS:
        server.tool()(fn)
    guidance.attach(server)
    return server


def main() -> None:
    first_run()
    build().run(transport="stdio")


if __name__ == "__main__":
    main()
