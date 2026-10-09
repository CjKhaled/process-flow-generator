---
id: hub_vendors
title: Hub operating models, vendors and systems
---

# Hub operating models, vendors and systems

## Operating models

Who runs the hub shapes the lanes of every flow. Programs use one of these, or a mix:

| Model | What it looks like | What it means for the flow |
|---|---|---|
| **In-house** | The manufacturer's own team keys forms and owns cases in its CRM | Lanes are internal roles. Most steps are visible to the user |
| **Outsourced hub** | A vendor runs intake and some or all case management | The vendor is a lane. Its internal steps may be partly invisible to the user |
| **Specialty pharmacy as hub** | The dispensing pharmacy also does enrollment or benefits work | The pharmacy lane carries hub work |
| **Hybrid** | A vendor does intake and first outreach, internal staff own the relationship | Work changes lanes mid-flow. Who owns which part is a key question |

Hybrid is common. A typical split: the vendor keys the form, checks duplicates and eligibility,
and sends the first missing-information fax; the manufacturer's case owner takes over patient
contact, consent and conversion.

## Vendor-mastered records

When a vendor creates and masters records in its own system and feeds the CRM, the client's
view of "a record is created" or "the patient converts" may really be an inbound data event:
a status or milestone arriving through an integration. The decision behind it happens inside
the vendor's process, which the user may not be able to describe in detail. That's fine:
capture what the user can see, and ask what they know about the vendor side.

## Integration layers

Data usually moves between the vendor's system and the CRM through a middleware or integration
layer. Users often name it as if it were a team ("it goes to X, and X sends it to the CRM").

- Some teams draw the integration layer as its own lane, because the hand-off is where things
  get lost. Others treat it as plumbing. Ask which the user wants rather than deciding.
- Statuses passed through it often trigger automation on arrival (a case or task is created).
  Those triggers are worth capturing: they're how the vendor's work turns into the client's work.

## Recognising names you don't know

A description will often contain names that appear nowhere in the glossary. They're usually one
of these:

- **A vendor or team**: performs work, so it becomes a lane.
- **A system or platform**: either a lane (if work is attributed to it) or context.
- **A system nickname**: a second name for a system already mentioned. A user may call the same
  CRM by two names in one description.
- **A form, task, status or object name**: context, never a lane.

Never guess which. Ask once, plainly: "What is X: a team, a vendor, a system, or something
else?" If the user has already used two names that might be the same system, ask whether they
are.

## What users often can't describe

- Steps inside the vendor's own process.
- How the vendor decides duplicates, restarts or eligibility.
- Exactly what triggers a status to be sent.

Recording "the vendor decides this; internal steps unknown" is a valid answer and better than
an invented step.
