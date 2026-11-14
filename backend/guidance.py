"""The onboarding, ask and journal guidance, for people without the plugin.

The three skills in jyotisha-plugin/ are the single source. A friend using the
shared server has no plugin, so the server hands out the same text itself, as
prompts and through the `guidance` tool. Nothing is restated here: edit the
skill and both routes change. The voice is not in these files at all -- that
is SYSTEM_RULES in advisor.py.
"""
from __future__ import annotations

import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "jyotisha-plugin" / "skills"
TOPICS = ("onboard", "ask", "journal")

# The skills address Claude Code. Where a line only makes sense there, this
# is appended rather than the skill being rewritten.
NOTE = ("\n\nIf a skill named above is not available to you, carry on "
        "without it.")


def text(topic: str, question: str = "") -> str:
    if topic not in TOPICS:
        raise ValueError(f"topic must be one of {', '.join(TOPICS)}")
    body = (SKILLS / topic / "SKILL.md").read_text(encoding="utf-8")
    # Drop the frontmatter: it tells Claude Code when to load the skill.
    body = re.sub(r"\A---\n.*?\n---\n", "", body, flags=re.DOTALL).strip()
    if question.strip():
        body = body.replace("`$ARGUMENTS`", f'"{question.strip()}"')
    else:
        body = re.sub(r"^The question is `\$ARGUMENTS`\..*$",
                      "If they have not said what they are weighing, ask.",
                      body, flags=re.MULTILINE)
    return body + NOTE


def attach(server) -> None:
    """Give a server the guidance tool and the three prompts. Used wherever
    Claude has the tools but not the plugin: the shared server and the
    Claude Desktop extension."""
    from mcp.server.mcpserver.exceptions import ToolError

    @server.tool()
    def guidance(topic: str) -> str:
        """How to do the three things this advisor is for. Read the relevant
        one before doing it for the first time in a conversation.

        topic is "onboard" (set up a profile: birth data, how well the time is
        known, life events), "ask" (advise on a decision) or "journal" (review
        past advice, record choices and outcomes).
        """
        try:
            return text(topic)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @server.prompt(name="onboard", title="Set up a profile",
                   description="Add yourself or someone close to you: birth "
                               "data, how well the time is known, life events.")
    def onboard() -> str:
        return text("onboard")

    @server.prompt(name="ask", title="Ask about a decision",
                   description="Get a timed answer on a choice you are weighing.")
    def ask(question: str = "") -> str:
        return text("ask", question)

    @server.prompt(name="journal", title="Review the journal",
                   description="Look back over past advice and record how "
                               "things turned out.")
    def journal() -> str:
        return text("journal")
