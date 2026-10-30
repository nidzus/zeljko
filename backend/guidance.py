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
