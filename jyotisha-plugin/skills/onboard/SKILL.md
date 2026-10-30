---
description: Set up a jyotisha profile — collect birth data, work out how well the birth time is known, and record life events. Use when someone wants to add themselves, a partner or a family member to the jyotisha advisor, or when a tool reports that no profile exists yet.
---

# Setting up a profile

Collect four things conversationally. Do not present it as a form.

## 1. Who

Their name, and whether this is themselves, a partner, family, or a friend.

## 2. Where they were born

Try `search_places` with the city name first. Show the matches with their
countries and let them pick — city names repeat across countries and picking
the wrong one moves the chart.

If the birthplace is a village the database does not carry, ask them to
right-click the spot in Google Maps and paste whatever it gives them, then use
`parse_coordinates`. Any format works. Tell them a hospital rather than a city
centre changes almost nothing, so a rough pin is fine — the point is coverage,
not precision.

## 3. When

The **local clock time** as it was recorded at the birthplace. Say that
explicitly. Do not convert anything yourself: historical timezone rules,
including offsets that no longer exist, are applied by `create_profile`.

## 4. How well that time is known

This is the step that matters most, and the one people wave through. Ask
directly and offer the actual options:

- **EXACT** — from a birth certificate or hospital record
- **RECTIFIED** — already refined against dated life events
- **REMEMBERED** — a time someone remembers being told
- **TO_THE_HOUR** — known to about the hour
- **VAGUE** — a family story: "in the morning", "around dinner"

Explain why you are asking: it decides what the advisor is later allowed to
claim. An overstated confidence quietly licenses advice the birth time cannot
carry, and nothing downstream will flag it. If they are unsure between two,
take the looser one.

## Creating it

Call `create_profile`. Then **read the warnings in the response**.

If the local time never occurred, the clocks went forward through it — the
recorded time is wrong somewhere and needs checking with whoever supplied it.
If it occurred twice, the clocks went back and the two readings give different
charts. Neither can be resolved by guessing. Say what happened and ask.

If it reports using the birthplace's local mean time, the birth predates
standard time in that region. Mention it in passing; it is correct behaviour,
not a problem.

## Life events

Then ask for five to ten dated things: job changes, moves, marriages, losses,
illnesses, the years something turned. Record each with `add_life_event`.

Say why, because it sounds like paperwork and is not. They give the advisor a
history to reason from immediately, and they are the evidence any later
birth-time rectification is tested against. Someone with a VAGUE birth time who
supplies good life events can eventually have a usable chart; someone without
them cannot.

Finish by calling `chart_context` and telling them what their chart supports
and what it does not, so the first refusal they meet is not a surprise.

## If the birth time is loose

Once five or more events are recorded, `propose_rectification` can narrow an
uncertain time by testing candidates against them. Offer it; do not run it
unasked.

Report what it returns honestly. It will often say the events do not
distinguish between the candidates, and that is a real answer -- pass it on
rather than picking the top of a list that is inside the noise. Where the
window spans more than one lagna, say so: those are different charts, not
variations on one.

Only call `apply_rectification` once they have explicitly accepted a
candidate. It stores a new version beside the original and marks it RECTIFIED,
which is deliberately treated as less reliable than a certificate time -- an
inference is not a record.
