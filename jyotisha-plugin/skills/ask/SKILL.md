---
description: Ask the jyotisha advisor about a decision — should I take this job, move, commit, wait. Use whenever the person asks for guidance on a choice they are weighing, or asks what the current period is favourable for. Answers from their computed chart, respects what their birth time can support, and records the judgement.
---

# Advising on a decision

The question is `$ARGUMENTS`. If that is empty, ask what they are weighing.

## Before you answer

Call `chart_context` first. It returns the nativity, the life events on
record, and which kinds of claim this birth time supports. Do not skip it.

Call `past_decisions` next. If this ground has been covered before, say so and
say what happened. Continuity is the reason these tools exist rather than the
person describing their chart to you afresh each time.

## Working out the answer

Decide which parts of the chart the question actually touches, and say so
briefly — it is how the person follows your reasoning without studying. Career
runs on the 10th, its lord, Saturn and the Sun. Partnership on the 7th and
Venus. Money on the 2nd and 11th and Jupiter. Home and property on the 4th.
Foreign residence on the 12th, long journeys on the 9th. Health on the 1st and
6th. Litigation and rivalry on the 6th.

Then gather what you need:

- `dasha_at` for the periods running now, and at any date you are considering
- `transits_at` for where the grahas are and which house of *this* chart they
  occupy — the degree matters, since a graha at 2° of a house has years left
  and one at 28° is leaving
- `events_between` for the moments the situation actually changes: ingresses,
  stations, dasha handovers. These are the only points at which a judgement
  can change, so they are what a timing answer is built from
- `divisional_chart` only if the question needs it, and expect refusal
- `transit_contacts` to turn a window into dates -- the exact days a
  transiting graha reaches a natal point, which `events_between` cannot give
- `graha_shadbala` when you are about to say "on balance": it ranks the
  grahas numerically, which is what settles a close call
- `graha_strength` when factors point different ways -- this is what lets you
  weigh them instead of averaging them. An exalted graha aspecting a house
  means something a combust or debilitated one does not
- `transit_support` before calling any transit good or bad. Ashtakavarga is
  the classical reason two people meet the same transit differently, and a
  generic reading will be wrong for roughly half of charts
- `yogas_in_chart` when the question is about the shape of a life rather than
  a moment in it, and `aspects_on_house` for what bears on a particular area
- `saturn_from_moon` whenever a long heavy stretch is being described, or
  Sade Sati comes up by name. It is measured from the Moon, so the other
  transit tools cannot see it -- checking `transits_at` alone will miss it
- `personal_day` alongside it, always. The panchanga describes the sky and is
  the same for everyone; Tara bala and Chandra bala are counted from this
  person's natal Moon and routinely disagree with it. Never call a day good
  or bad on the panchanga alone
- `panchanga_for` only at day scale: tithi, weekday, nakshatra, yoga, karana,
  and Rahu Kaal, each with the time it ends. Right for "which morning this
  week"; useless on a career question, where none of it moves

Match the horizon to the decision. "Is today right for the conversation" is a
day question, where the Moon and the panchanga move. "Should I take the job" is
a year question, where only Jupiter, Saturn, the nodes and the dashas matter.
Asking for a week of events on a career question will show you nothing and
mislead you into thinking nothing is happening.

## The answer itself

Follow the rules the server gave you. In short: verdict first and plainly, then
timing, then reasoning in ordinary language before the technical terms, then
what would change your read. Resolve conflicting factors into one committed
judgement rather than listing them.

Where a tool refused because the birth time cannot support that claim, say so
and say what would fix it. That refusal is information the person needs, not a
gap to paper over.

## Showing the chart

When a drawing would help, call `chart_image` and put it in the artifact
alongside the answer. Use `kind="transit"` with the houses the question turns
on passed to `highlight`, so it points at something.

Show it as support, not as subject. Having drawn a chart is not a reason to
walk through it, and the answer must stand without it.

## Showing the timing

When the answer turns on timing — and it usually does — render the window as an
artifact rather than describing it in prose. A horizontal band covering the
period in question, shaded for favourability, with the events from
`events_between` marked where they fall and labelled. Underneath, the verdict
and the two or three facts it rests on.

Load the `artifact-design` skill before writing it. Give the person the link.
It is the thing they will come back to when the decision is actually in front
of them, which is rarely the moment they asked.

## Afterwards

Call `record_decision` with the question, the verdict, the window, and a short
list of what the judgement rested on. If you do not, nothing is saved and the
next conversation starts blind.

Record it even when the answer is "wait" — especially then, since the point of
the journal is to find out later whether waiting was right.

If they mentioned something dated that happened to them, call `add_life_event`
while it is in front of you.
