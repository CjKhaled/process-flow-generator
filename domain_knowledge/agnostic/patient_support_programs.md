---
id: patient_support_programs
title: Patient support programs
---

# Patient support programs

## What a PSP is

A patient support program (PSP) is a service a drug manufacturer funds to help patients start
and stay on a therapy. It usually exists because the drug is expensive, hard to get covered,
hard to administer, or prescribed for a rare condition. The program helps with access
(insurance), affordability (copay and free drug), and support (education, nurses, adherence).

The operation that runs the program is usually called the **hub**. It may be run by the
manufacturer's own team, by an outsourced vendor, by the specialty pharmacy, or a mix. See
`hub_vendors.md`.

Programs are usually built on a CRM (often Salesforce Health Cloud or Life Sciences Cloud),
and many terms users say are really object or status names from that CRM.

## The patient journey

The business processes follow the patient, roughly in this order. Each is modelled as its own
process, connected by hand-offs:

| Process | What happens | Typical hand-off out |
|---|---|---|
| **Intake & enrollment** | A submission arrives, is keyed, screened, completed and becomes an enrolled patient | To benefits investigation |
| **Coverage determination** | Benefits investigation or verification, prior authorization, appeals | To financial assistance, or to dispensing |
| **Financial assistance** | Copay programs, free drug (PAP), bridge and quick start | To dispensing |
| **Dispensing** | The specialty pharmacy fills and ships | To ongoing support |
| **Ongoing support** | Adherence, refills, nurse education, re-verification, re-enrollment | Back to coverage determination at renewal |

Real programs overlap these. Benefits investigation often starts before enrollment finishes,
and a quick start may ship while coverage is still being worked. When the user describes work
that belongs to a neighbouring process, the session captures that the hand-off happens and
where it goes, not the neighbouring process's detail.

## Pharmacy-dispensed vs buy-and-bill

Pharmacy-dispensed products are shipped by a specialty pharmacy to the patient or clinic.
Buy-and-bill products are bought and administered by the clinic, which then bills the payer.
The access processes differ a lot. These knowledge files cover pharmacy-dispensed products.

## Who's involved

The same work is done by very different job titles across programs. The session models
**responsibilities**, not titles: see `personas.yaml`. Typical parties are the HCP office, the
patient or caregiver, an intake or data entry team, a case owner who owns the patient
relationship, field staff who visit offices, nurses or clinical educators, the specialty
pharmacy, and the CRM and its automations.

## What users describe, and how

Users describing a PSP process usually:

- Describe the happy path in detail and stop before saying what happens when something fails.
- Use CRM object names, statuses and task names as if they were steps.
- Mix in-house and vendor work without saying which is which.
- Describe automation in the passive voice ("a task is created", "the PSM is assigned").
- Say "enrolled" meaning different states: converted, fully enrolled, or receiving services.

None of these are errors to correct. They're the reason the session asks follow-up questions.

## Pain points seen across programs

These come up in nearly every program. They're worth recording when the user mentions them,
as said, but never raised as suggestions:

- Fax is still the main intake channel and is largely keyed by hand.
- Duplicates persist despite search-first rules.
- Nobody can see who has picked up which submission.
- Tasks are left open or closed inconsistently, and it's unclear which automation created which task.
- Missing information isn't flagged automatically.
- Staff check two places (vendor system and CRM) for one patient.
