---
id: lead_conversion
title: Lead conversion, assignment, welcome and exits
---

# Lead conversion, assignment, welcome and exits

Covers the second half of intake: becoming enrolled, being assigned to a care team, being
welcomed, and leaving the process. Topics: `conversion.*`, `routing.*`, `welcome.*`, `nurse.*`,
`rems.*`, `exit.*`.

## Why missing information drives conversion

Conversion happens when the record holds what the program defines as required. Everything missing
becomes outreach, so the conversion criteria and the missing-information flows are two views of
the same rule set. When the user describes conversion criteria, the natural next question is how
each missing criterion gets chased, and vice versa.

Watch for two tiers of requirements:

- **Required to convert.** Typically identity, consent, the HCP's submission, and sometimes the
  prescription or a passed eligibility check.
- **Required later.** Things needed downstream (insurance details, clinical documentation for
  prior authorization) that don't block conversion.

Users often blur these. "What has to be in place before someone is considered enrolled?"
separates them.

## Conversion in a flow

Conversion usually shows up as a gateway ("Everything obtained?") followed by a conversion step,
done by a person or by automation. The criteria are rules on that gateway, not separate steps: if
the user lists five criteria, that's one gateway with a combined condition, unless they describe
different outcomes for different missing criteria.

What conversion creates (records, milestones) is usually a record detail. The exception is
conversion that **kicks off downstream work**, for example a benefits investigation case or a
welcome-call task created at conversion, which changes what happens next and so is part of the flow.

## Partial enrollment

Where patients or pharmacies can start an enrollment, programs usually allow a reduced state
until the HCP side, a signature or a prescription arrives. The patient may get some support
(education, general support) but not the full set of services. It shows up as a branch at
conversion: full criteria met leads to full enrollment, partial criteria to the partial state, and
a later event upgrades it. The upgrade trigger often comes from a lane the user hasn't mentioned
yet, such as the specialty pharmacy sending a prescription.

## After conversion

- **The original record.** Locked, closed or left open, and its open tasks closed or not. Leftover
  open tasks are a recurring pain point; if the user mentions them, capture what actually happens,
  including "they stay open".
- **Tasks closing in sequence.** Many programs chain tasks: closing "collect missing information"
  triggers "make welcome call" and "send welcome materials". Who closes each task, and whether
  it's manual, is worth capturing.

## Assignment and territory routing

Ownership is usually assigned by ZIP code to a territory and its care team, often automatically
when a status arrives. Which ZIP drives it (patient's, prescriber's, or prescriber's with the
patient's as fallback), which roles get assigned (case owner, nurse, field reimbursement, field
sales), what happens when no territory matches, and how territory changes reach existing patients
all vary.

## Nurse program enrollment

Applies when the program has nurse or educator support. See
`../agnostic/product_considerations.md`.

## REMS at intake

Applies when a product has a REMS. See `../agnostic/rems.md`.

## Welcome outreach

A welcome call, welcome materials, or both, sometimes with a separate clinical welcome call in
parallel. Often gated: by consent, by the HCP signature, or by conversion. What happens when the
patient can't be reached for the welcome call is often undefined.

## Exits

- **Hand-off to benefits investigation.** Triggered by a task or flag when missing information
  closes, opened manually by the case owner, started by a vendor when the file is complete, or
  created at conversion and run in parallel. Programs split on whether benefits investigation can
  start while enrollment is incomplete: always ask.
- **HCP told of the outcome.** Some programs notify the office on enrollment; most notify on
  closure.
- **Not enrolled.** Never started, cancelled for missing consent or information, unable to reach,
  declined, or ineligible and not redirected.

## Seen across programs

From five programs. "Seen before", never a norm, never said to the user.

- Partial enrollment then upgrade: 4 of 5 (the fifth only accepts HCP submissions). Upgrade on the
  HCP form, the patient's signature, or a prescription from the pharmacy, one each.
- ZIP-based routing: all 5 (patient ZIP 2, HCP ZIP with patient fallback 1).
- Tasks left open or closed inconsistently: 3 of 5.
- Welcome (3 described): welcome call 2, welcome materials 1 (gated by consent), parallel clinical
  call 1.
- Benefits investigation while enrollment is incomplete (5 described): allowed 3, gated 2.

## Common confusions

- "Enrolled" means different things: converted, fully enrolled, or receiving services.
- Some programs check eligibility before conversion, some after. Ask rather than assume the order.
- "The lead converts" can be a button press or an automatic rule. The lane depends on which.
