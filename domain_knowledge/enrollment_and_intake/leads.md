---
id: leads
title: Leads, records and prescriber linking
---

# Leads, records and prescriber linking

Covers what record is created for a person, where it lives, how data moves between systems,
and how the prescriber is linked. Topics: `record.*`, `prescriber.*`. Conversion of a lead into
an enrolled patient is in `lead_conversion.md`.

## What a lead is

A lead is a preliminary record for someone who has been referred but isn't enrolled yet. It lets
the program hold incomplete, unconsented or unverified information without creating a patient
record too early. Programs use many names for the same idea: lead, referral, inquiry, prospect,
pending account, or an account type such as "marketing only". Treat them as one concept, and use
whatever the user calls it.

## Three record models

- **Lead-first.** Everything starts as a lead. Nothing becomes a patient until a conversion step
  passes a checklist. Where most programs on modern CRM platforms are heading.
- **Patient-first.** The patient account is created directly, usually in a pending status. A
  lead-like state often still exists under another name; then the question becomes "what moves
  someone out of that state?"
- **Vendor-mastered.** An external vendor creates and masters records in its own system and feeds
  the CRM. The client's view of "a record is created" may be an inbound data event. See
  `../agnostic/hub_vendors.md`.

The record model shapes the whole main line, so it's worth settling early (`record.model`).

## Product-level enrollment records

Programs commonly keep one person record plus a separate enrollment record per product (often a
care plan or "care program enrollee product"), carrying status, sub-status and milestones.

- Status changes on that record are often what the user means by "the patient moves to…".
- Status and sub-status values ("PENDING", "NEW PATIENT – HUB ENROLLED") are record values:
  annotations, not steps.
- A returning patient enrolling in a second product creates a new enrollment record, not a new
  patient. That's a duplicate-handling outcome.
- Users sometimes complain about checking two places for one patient: a pain point, not a step.

## Data moving between systems

In vendor and hybrid models, records and statuses move from the vendor's system through an
integration layer into the CRM, and their **arrival triggers work**: a case is created, a task is
generated, an owner is assigned. Those triggers are some of the most important hand-offs in the
flow, and users describe them in a sentence ("this status is sent to X, which sends it to the
CRM, which creates the onboarding case"). Each actor that moves or acts on the data is worth
capturing in its own lane, if the user treats it as one.

## Prescriber lookup and link

The prescriber (and their practice) is found in master data and linked to the record, usually by
NPI, sometimes tax ID, or name and address. Sources: an NPI registry search, an HCP master data
service, or a local CRM search. When the prescriber isn't found, programs create a local record,
create one from the NPI automatically, request a master-data addition, or block until resolved.
Creating local records is common and is sometimes described as undermining master data.

## Seen across programs

From five programs. "Seen before", never a norm, never said to the user.

- Record model (5 described): lead-first 2 (a third migrating toward it), patient-first 2 (one
  with an account type that behaves like a lead), vendor-mastered 1.
- One person record plus a product-level enrollment record: all 5.
- Prescriber lookup (5 described): NPI registry 3, master data service 2. Local record when not
  found: 3.

## Common confusions

- "Enrolled" can mean converted, fully enrolled, or receiving services. Ask which, when it matters.
- A record being created is not the same as the patient being enrolled.

## Often left out

- Which system the first record is created in, when there's more than one.
- What the arrival of a status or record triggers in the receiving system.
- What happens when the prescriber can't be found.
