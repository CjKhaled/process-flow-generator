---
id: rems
title: REMS
---

# REMS

## What it is

A Risk Evaluation and Mitigation Strategy (REMS) is a drug safety program the FDA can require for
products with serious risks. Many REMS only require communication (medication guides, letters to
prescribers). Some add **Elements to Assure Safe Use (ETASU)**, which put conditions on who can
prescribe, who can dispense, and what has to happen before the drug reaches the patient.

A REMS is usually run by a **REMS administrator** (often a call center or website operated for
the manufacturer), separate from the patient support program. The two often share information,
but they're different programs with different rules.

## What ETASU can require

| Requirement | Example |
|---|---|
| Prescriber certification | The prescriber completes training and enrolls before prescribing |
| Pharmacy certification | Only certified pharmacies may dispense |
| Patient enrollment | The patient enrolls in the REMS, sometimes signing an agreement with the prescriber |
| Testing before dispense | A lab result (for example a pregnancy test or blood count) is documented first |
| Vaccination before dispense | Required vaccinations are documented before the first dose |
| Safety materials | A safety card or counselling is provided |
| Monitoring | Ongoing tests or checks while on therapy |

## What it means for intake

Mostly, REMS requirements gate **dispensing**, not enrollment. A patient can often be enrolled in
the support program while REMS items are still outstanding. But programs differ:

- Some track REMS status in the hub and won't move a patient to benefits investigation or
  shipment until it's complete.
- Some collect REMS forms through the same intake channels as enrollment forms.
- Some leave REMS entirely to the REMS administrator and the pharmacy, and the hub only sees
  the outcome.

So the useful questions are: which REMS items come up during intake, who tracks them, and
whether an incomplete item changes anything about enrollment or only about dispensing.

## How it shows up in a flow

- REMS forms received at intake are documents, not steps, unless someone does work with them.
- A REMS check that blocks progress is a gateway, in the lane of whoever checks.
- REMS administrator work the user can't see is captured as a hand-off, not invented steps.

## Applies only when

The program has at least one product with a REMS (`product.has_rems`). Until that's known, the
REMS topics stay in the checklist, asked once through the screening question.
