"""Checks on the advisor's guardrails.

None of this needs an API key. What is being tested is not the model -- it is
everything that constrains the model, which is where the correctness lives.
"""
import sys
sys.path.insert(0, ".")

import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from backend import tools
from backend.advisor import SYSTEM_RULES, Advisor
from backend.confidence import TimeConfidence
from backend.store import Store

results = []
BG = (44.7866, 20.4489)


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


def make_store(confidence):
    store = Store(Path(tempfile.mkdtemp()) / "adv.db")
    pid = store.add_person("Reference")
    store.add_chart(pid, 1988, 3, 12, 16, 30, 0, "Belgrade, RS", *BG, confidence)
    store.add_life_event(pid, "2011-04-15", "Changed career", category="career")
    return store, pid


# --------------------------------------------------------------- the gate

print("=" * 72)
print("1. A divisional chart the birth time cannot bear is refused")
print("   Not discouraged in the prompt -- refused by the tool, so no wording")
print("   the model chooses can get the data out.")
store, pid = make_store(TimeConfidence.REMEMBERED)
runner = tools.ToolRunner(store, pid)
d9 = runner.divisional_chart(varga=9)
check("navamsa refused at ±15 min", d9.get("refused") is True,
      d9.get("reason", "")[:96])
check("the refusal explains the remedy", "rectification" in d9.get("reason", "").lower())

store_x, pid_x = make_store(TimeConfidence.EXACT)
runner_x = tools.ToolRunner(store_x, pid_x)
d9x = runner_x.divisional_chart(varga=9)
check("navamsa allowed at ±1 min", not d9x.get("refused"),
      f"D-9 lagna {d9x.get('lagna')}")
d60x = runner_x.divisional_chart(varga=60)
check("shashtiamsa still refused even at ±1 min", d60x.get("refused") is True,
      "D-60 moves every two minutes; almost no chart supports it")

print()
print("=" * 72)
print("2. Dates are rounded at source, not in the wording afterwards")
dasha = runner.dasha_at(date="2026-11-15")
periods = dasha["periods"]
check("precision travels with the result",
      dasha["date_precision"] == "to the month", dasha["date_precision"])
check("dates are given as months, never as days",
      all(not p["begins"][:4].isdigit() or "-" not in p["begins"] for p in periods),
      "; ".join(f"{p['lord']} {p['begins']}–{p['ends']}" for p in periods))

print()
print("=" * 72)
print("3. A birth time supporting nothing yields no dasha dates at all")
store_v, pid_v = make_store(TimeConfidence.VAGUE)
runner_v = tools.ToolRunner(store_v, pid_v)
vague = runner_v.dasha_at(date="2026-11-15")
check("the tool refuses outright", vague.get("refused") is True,
      vague.get("reason", "")[:96])
ev = runner_v.events_between(start="2026-01-01", end="2027-01-01",
                             bodies=["Jupiter"])
kinds = {e["kind"] for e in ev["events"]}
check("dasha handovers are dropped, transits kept",
      "dasha" not in kinds and "ingress" in kinds, f"kinds present: {sorted(kinds)}")

print()
print("=" * 72)
print("4. Transits are reported against this nativity, with position in sign")
tr = runner.transits_at(date="2026-11-15")
sat = next(p for p in tr["positions"] if p["body"] == "Saturn")
check("every graha carries a house of the nativity",
      all(1 <= p["house_of_nativity"] <= 12 for p in tr["positions"]))
check("degree within the sign is included",
      "degrees_in_sign" in sat,
      f"Saturn {sat['degrees_in_sign']}° {sat['sign']}, "
      f"house {sat['house_of_nativity']}, retrograde {sat['retrograde']}")

print()
print("=" * 72)
print("5. Bad tool calls fail loudly rather than silently")
check("unknown tool", "error" in runner.call("read_minds", {}))
check("wrong arguments", "error" in runner.call("dasha_at", {"when": "2026"}))
bad = runner.events_between(start="2026-01-01", end="2026-06-01",
                            bodies=["Pluto"])
check("unknown body refused", bad.get("refused") is True)

print()
print("=" * 72)
print("6. Every result is recorded under a fact id")
check("ids issued in order and stored",
      list(runner.facts) == [f"f{i}" for i in range(1, len(runner.facts) + 1)],
      f"{len(runner.facts)} facts recorded: {list(runner.facts)}")

# ---------------------------------------------------- the citation contract

print()
print("=" * 72)
print("7. Citations are checked against what the tools actually returned")


class FakeClient:
    """Stands in for the API: one tool call, then an answer with citations."""

    def __init__(self, answer_text):
        self.answer_text = answer_text
        self.turn = 0
        self.systems = []
        self.messages_seen = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.turn += 1
        self.systems.append(kw["system"])
        self.messages_seen.append(kw["messages"])
        usage = SimpleNamespace(input_tokens=100, output_tokens=50,
                                cache_read_input_tokens=0,
                                cache_creation_input_tokens=900)
        if self.turn == 1:
            block = SimpleNamespace(type="tool_use", id="tu_1", name="dasha_at",
                                    input={"date": "2026-11-15"})
            return SimpleNamespace(content=[block], stop_reason="tool_use",
                                   usage=usage)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.answer_text)],
            stop_reason="end_turn", usage=usage)


store2, pid2 = make_store(TimeConfidence.REMEMBERED)
fake = FakeClient("You are in the Mars mahadasha [f1]. Also Jupiter "
                  "favours you [f7].")
advisor = Advisor(store2, pid2, client=fake)
answer = advisor.ask("Should I change jobs?", today=date(2026, 8, 27))

check("the tool loop ran and returned an answer", fake.turn == 2
      and "mahadasha" in answer.text)
check("the tool it called was recorded", answer.tool_calls == ["dasha_at"])
check("a real citation is accepted", "f1" in answer.cited)
check("an invented citation is caught", answer.fabricated == ["f7"],
      f"fabricated: {answer.fabricated}")
check("and the answer is marked unclean", answer.clean is False)

print()
print("=" * 72)
print("8. The cached prefix is stable and the volatile date is outside it")
system = fake.systems[0]
check("the cache breakpoint sits at the end of the stable block",
      system[-1].get("cache_control") == {"type": "ephemeral"})
# The real risk is a date that CHANGES between requests. A constant
# string is harmless; today's date here would cost money every day.
check("today's date appears nowhere in the cached prefix",
      all("2026-08-27" not in block["text"] for block in system))
check("the current date is in the user turn instead",
      "2026-08-27" in fake.messages_seen[0][0]["content"])
check("both requests sent an identical system prefix",
      fake.systems[0] == fake.systems[1],
      "an unstable prefix would miss the cache on every request")

print()
print("=" * 72)
print("9. The answer is persisted as a decision, citations joined to facts")
did = advisor.record(answer, "Should I change jobs?")
stored = store2.citations(did)
check("only real citations are stored", len(stored) == 1,
      f"{len(stored)} citation(s); the invented one was not stored")
check("the stored citation carries the computed fact",
      "mahadasha" in stored[0]["fact"], stored[0]["fact"][:80] + "...")
decision = store2.decisions(pid2)[0]
check("the reliability at the time was frozen with it",
      "to the month" in decision["reliability"], decision["reliability"])

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
