---
id: channels
title: Submission channels, work pool and keying
---

# Submission channels, work pool and keying

Covers the start of intake: how a submission arrives, where it waits, and how it becomes system
data. Topics: `intake.*`, `sp.enrollment_role`.

## Channels

Submissions arrive as an enrollment form, a referral, or a patient's self-enrollment, through:

- Fax or e-fax (the dominant channel almost everywhere)
- HCP web form or e-sign portal
- Patient web self-enrollment
- Email or mail
- Specialty pharmacy referral
- Field-originated submissions, or phone

The key question isn't just which channels exist, but whether they **converge**. In many programs
every channel ends up keyed into the same record and follows one path. In others, a web form
creates records automatically while faxes are keyed by hand, and the paths only meet later.

## Patient self-enrollment and pharmacy referrals

Where patients or pharmacies can start an enrollment, the program has to decide what that person
gets before the HCP side arrives. That usually means a partial enrollment state: see
`lead_conversion.md`. A pharmacy may also send the prescription that completes or upgrades an
enrollment, or receive patients the program can't enroll.

## Receipt acknowledgement

Some programs send the HCP office a confirmation that the submission was received (for example a
fax confirmation). It's easy to miss, because users describe it in passing. It's a real step in
the lane of whoever sends it.

## Work pool and claim

New submissions usually wait in a shared pool until someone takes ownership: a CRM unassigned
queue, a shared fax or email inbox, or a vendor's internal queue. Claiming varies: an explicit
accept, self-assign, automatic assignment, an alert to the owner, or no tracking at all.

## Keying

Someone (or something) turns the submission into system data: an in-house data entry team, a hub
vendor, an external vendor working upstream of the CRM, or automated extraction with a person
resolving low-confidence fields. The keying role usually **does not** own the patient relationship
and often never contacts the patient or office.

Some programs run all incoming paperwork (appeals, insurance cards, income documents) through the
same intake pipeline, not just enrollment forms. Those other documents are recognised but not
modelled in intake.

## Documents that arrive at intake

The enrollment form (PEF) is the core document, usually with numbered sections for the HCP and
patient; programs often refer to them by number ("sections 1, 2, 5 or 6"). The patient consent or
HIPAA authorization is often a section of the form rather than a separate document. Prescriptions,
insurance cards, clinical documentation and medical necessity statements may arrive with it or
separately. A document mentioned in a step is context, not a step.

## Seen across programs

From five programs. "Seen before", never a norm, never said to the user.

- Channels (5 described): fax 5, HCP web form or e-sign 5, patient self-enrollment 3, email 2,
  mail 2, specialty pharmacy referral 2.
- Specialty pharmacy involvement in enrollment appeared in 4 of 5.
- Who keys (5 described): hub vendor 2, vendor upstream of the CRM 1, in-house 1, automated
  extraction with human review 1.
- Keying automation (5 described): none 3, OCR prefill 1, document AI covering all paperwork 1.
- Keying and the patient relationship were separate roles in all 5.
- Claim model (4 described): explicit accept, self-assign, no tracking, alert to owner, one each.

## How it shows up in a flow

- One start node, even with several channels: the channels go in the start's label and detail.
- A channel-specific path is a gateway only if the user describes different steps per channel.
- The keying step sits in the lane of whoever keys.

## Often left out

- Whether every channel ends up on the same path.
- Where work waits before anyone picks it up, and whether anyone can see who has it.
- Whether the office hears back that the submission arrived.
- Who resolves the fields automation couldn't read.
