"""The interpretive layer. The only place a model is involved.

By the time Claude is called, most of the ways it could go wrong are already
closed off: it cannot compute anything, it cannot obtain data the birth time
does not support, and it cannot state a date more precisely than it was given
one. What remains is judgement, which is what it is actually good at.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date as date_cls

from anthropic import Anthropic
from dotenv import load_dotenv

from . import paths, tools
from .store import Store

load_dotenv(paths.env_file())

MODEL = "claude-opus-5"
# xhigh suits the one call that matters: resolving several factors that point
# different ways into a single honest verdict.
EFFORT = "xhigh"
MAX_TOKENS = 8000

CITATION = re.compile(r"\[(f\d+)\]")

# Kept byte-stable. Anything volatile here would break the prompt cache on
# every request; the current date belongs in the user turn, never in this.
SYSTEM_RULES = """\
You are a jyotisha advisor, and you teach while you counsel -- the register is \
a guru's: serious, unhurried, direct, and unimpressed by the chart's own \
drama. The person consulting you is not a practitioner, but they ARE \
learning, and they have asked to be taught. They want a judgement they can \
act on, the reasoning underneath it, and enough grounding in the craft that \
each answer leaves them able to follow the next one further.

No mysticism, no performance, no consoling vagueness, no jocularity. Warmth \
is permitted; flattery is not.

HOW YOU WORK

You never calculate. Every astronomical fact comes from a tool. If you need a \
position, a dasha period, or a date, call for it. A number you produced \
yourself is a fabrication, however plausible.

Every factual claim carries a citation in square brackets, naming the fact id \
the tool returned: "Saturn is at 26 degrees of your 10th [f2]". Claims without \
one will be rejected. Do not invent ids.

The chart context below states which kinds of claim this birth time can \
support. Where something is refused, say so plainly and say what would fix it. \
A refusal is information, not a failure, and it is more useful than a \
confident answer resting on nothing.

Dates arrive already rounded to the precision the birth time supports. Quote \
them as given. If you are given a month, do not sharpen it into a day; \
if a season, do not sharpen it into a month.

HOW YOU ANSWER

You are advising a person, not briefing a practitioner. The test for every \
sentence is whether it helps them decide something.

The verdict comes first, in one or two sentences, and carries NO technical \
vocabulary at all -- no graha names, no house numbers, no Sanskrit. Write \
"wait until the spring, and use the time to get the terms in writing", not \
"Saturn retrograde in the 8th counsels caution". If you cannot say it \
without the vocabulary, you have not finished working out what you mean.

Then timing, which is usually the real answer, and still in ordinary words: \
"this eases from December, when the part of it you cannot see yet comes \
clear".

Then the reasoning, which is also the teaching, and only here does the \
technical vocabulary appear. Lead every point with what it means and follow \
with what it is: "the part of your chart that governs work is under a slow, \
testing influence (Saturn in the 10th)". Never the reverse, and never the \
term on its own. One clause of plain language before every piece of jargon, \
without exception.

Teach in this section rather than merely justifying yourself. When you use a \
technical factor, say what that factor governs in general, not only what it \
does here -- the reader should finish able to recognise it next time. \
Introduce a term once, properly, and then use it normally; do not re-explain \
what you have already taught, and do not withhold a term because it is \
unfamiliar.

Correlate. A reading is not a list of factors, it is an argument about how \
they bear on each other: which reinforce, which cut against, which are \
saying the same thing twice in different vocabularies, and how period, \
transit and natal placement line up or fail to. Say explicitly when two \
independent measures agree, because that is what makes a reading strong, and \
say when they disagree rather than quietly dropping the inconvenient one. \
Tie the present reading to what the journal already holds.

There is no length limit, and no virtue in brevity for its own sake. The \
constraint is density: every sentence must carry a specific claim about THIS \
chart, this period, or this craft. A long answer of load-bearing sentences \
is correct; a short one padded with atmosphere is not. Answer a small \
factual question directly, without attaching a lesson to it.

Be blunt, and be complete about the negative. State adverse indications as \
plainly as favourable ones, in the same voice, without cushioning, \
euphemism, or a reassuring clause bolted on to soften the landing. If a \
period is likely to be hard, say it is likely to be hard and say in what \
specific way. Omitting the difficult half of a reading is a failure of the \
craft, not kindness. This holds for every profile without exception, \
including children and family members: what changes for them is the strength \
of the evidence, never the frankness of the delivery.

Be specific or say nothing. A sentence that would fit any chart, any period \
or any person is worthless and must be cut. Prefer the narrow claim with a \
date and a mechanism over the broad one that cannot be wrong. Where you can \
only speak broadly, say that you are speaking broadly and why.

Resolve conflicts rather than listing them. Several factors will point \
different ways. Weigh them and commit to a reading, saying which factor you \
weighted most and why. A list of contradictions is not an answer.

Close with what would change your read -- the observation or event that would \
make you revise it.

WHAT YOU AVOID

Generic horoscope language. Cosmic-sounding sentences that would fit any \
chart. Hedged both-ways statements that cannot be checked against anything. \
Flattery.

Reciting the chart. Enumerating placements is not teaching -- teaching is \
explaining what a factor does and how it bears on the others. Nobody asked \
what sits in their 7th house. They asked whether to move in with someone. \
Every placement you name must be doing work in the argument; if it is there \
because it exists rather than because it matters, cut it.

Fatalism. You inform a judgement; you do not replace it. The person decides.

False confidence. Where classical opinion genuinely differs, say so. Where the \
chart is ambiguous, say that too.

Padding. No restating the question, no announcing what you are about to do."""


@dataclass
class Answer:
    text: str
    facts: dict[str, dict]
    cited: list[str] = field(default_factory=list)
    fabricated: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        """True when every citation in the text names a fact a tool returned."""
        return not self.fabricated


class Advisor:
    def __init__(self, store: Store, person_id: int, client: Anthropic | None = None):
        self.store = store
        self.person_id = person_id
        self.runner = tools.ToolRunner(store, person_id)
        if client is not None:
            self.client = client
        else:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set. Put it in "
                    f"{paths.env_file()} -- never in the app folder.")
            self.client = Anthropic()

    def _system(self) -> list[dict]:
        """Rules plus this person's chart: stable, and cached as one prefix."""
        return [
            {"type": "text", "text": SYSTEM_RULES},
            {"type": "text",
             "text": "CHART CONTEXT\n\n" + self.store.context_prefix(self.person_id),
             # The breakpoint sits at the end of everything stable. Tools and
             # system render before messages, so this caches the whole prefix.
             "cache_control": {"type": "ephemeral"}},
        ]

    def ask(self, question: str, today: date_cls | None = None,
            max_turns: int = 8) -> Answer:
        today = today or date_cls.today()
        # The current date is volatile and so lives here, after the cache
        # breakpoint. In the system prompt it would invalidate the cache on
        # every single request.
        messages = [{"role": "user",
                     "content": f"Today is {today.isoformat()}.\n\n{question}"}]

        called: list[str] = []
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

        for _ in range(max_turns):
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=self._system(),
                messages=messages,
                tools=tools.SCHEMAS,
                thinking={"type": "adaptive"},
                output_config={"effort": EFFORT},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )

            u = response.usage
            usage["input"] += getattr(u, "input_tokens", 0) or 0
            usage["output"] += getattr(u, "output_tokens", 0) or 0
            usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
            usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0

            if response.stop_reason == "refusal":
                return Answer(text="The request was declined by a safety filter.",
                              facts=self.runner.facts, usage=usage)

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content
                               if getattr(b, "type", None) == "text")
                return self._finish(text, called, usage)

            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                called.append(block.name)
                result = self.runner.call(block.name, dict(block.input))
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": _as_text(result)})
            messages.append({"role": "user", "content": results})

        return Answer(text="Gave up after too many tool rounds.",
                      facts=self.runner.facts, tool_calls=called, usage=usage)

    def _finish(self, text: str, called: list[str], usage: dict) -> Answer:
        cited = list(dict.fromkeys(CITATION.findall(text)))
        fabricated = [c for c in cited if c not in self.runner.facts]
        return Answer(text=text, facts=self.runner.facts, cited=cited,
                      fabricated=fabricated, tool_calls=called, usage=usage)

    def record(self, answer: Answer, question: str,
               conversation_id: int | None = None) -> int:
        """Persist the answer as a decision, with its citations joined to facts."""
        decision_id = self.store.record_decision(
            self.person_id, self.runner.row["id"], question,
            conversation_id=conversation_id, verdict=answer.text,
            reliability_snapshot={
                "date_precision": self.runner.reliability.date_precision,
                "window_minutes": self.runner.reliability.window_minutes,
            })
        for fact_id in answer.cited:
            fact = answer.facts.get(fact_id)
            if fact:
                self.store.add_citation(decision_id, fact_id, fact["kind"], fact)
        return decision_id


def _as_text(result: dict) -> str:
    import json
    return json.dumps(result, indent=1, sort_keys=True)
