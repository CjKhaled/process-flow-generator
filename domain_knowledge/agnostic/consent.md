---
id: consent
title: Consent
---

# Consent

## Why consent is the master gate

Most manufacturers and hubs aren't the patient's healthcare provider. To receive and use the
patient's health information, and to contact them, they rely on the patient's authorization.
That's why consent unlocks downstream work in nearly every program: without it, the program has
limited basis to act on what it has received. When a user describes what's blocked while
consent is outstanding, they're describing the program's legal and policy choices about that
basis. Capture them exactly (`consent.gate`).

## Types are separate on purpose

- **HIPAA authorization / program consent**: permission to share and use health information
  for the program. Usually required.
- **Program terms**: agreement to the program's rules. Usually captured with the above.
- **Marketing**: promotional contact. Optional, and never a condition of services.
- **Text messaging**: needed before text outreach, under telephone consumer protection rules.
- **Email**: needed before email outreach.
- **Nurse program, research or data use, third-party authorizations**: in some programs.
- **HCP attestation**: some programs treat the prescriber's attestation as a time-limited,
  consent-like item with its own expiry.

Programs split these because required and optional consents can't be bundled, and because each
governs a different channel or use.

## Methods

Electronic signature (link by email or text), signature on the enrollment form at the office,
paper mailed or couriered as a fallback, web click-through, verbal by phone, text reply, and
consent recorded directly by staff in the CRM. Nearly every program has an electronic route and
a fallback. When a user names only one method, ask whether there's another for patients who
can't use it.

## Verbal consent

Rules vary more than any other consent detail: not accepted, accepted once with a short
validity, accepted only for named third parties on one call, or excluded in some states.
Verbal consent often has to be followed by written consent within a window. If verbal consent
exists, the flow usually has a follow-up branch, and possibly an expiry that ends the enrollment.

## Representatives and minors

A caregiver who helps is not automatically a legal representative. Programs differ on how
authority is established: documents verified by a manager, power of attorney self-attested on
the form, or parent consent for minors. A minor turning 18 must consent for themselves. Some
programs set consent validity to end at that birthday.

## Validity, expiry and renewal

Validity ranges from weeks (for specific consents or verbal consent) to many years. What happens
at expiry differs: a renewal task ahead of time, a warning, unenrollment, or restricting access
to the patient's data until renewed. Renewal can arrive as a whole new enrollment form that
goes through the duplicate check and merges into the existing record, or be recorded directly
by staff.

Expiry and renewal mostly happen long after intake. Capture them only as far as intake is
involved, for example a renewal form that re-enters through the intake channels.

## How consent shows up in a flow

- Capture is usually part of the submission (a form section), or a separate e-sign request sent
  by automation after keying.
- A gateway checks for consent before conversion, benefits investigation or welcome outreach.
  Where that gateway sits on the main line is one of the most important things to get right.
- Missing consent is chased in the patient missing-information flow, often with its own deadline
  and a cancellation outcome.
- Text or email outreach anywhere in the flow implicitly depends on the matching consent. If the
  user describes texting patients, it's fair to ask once, openly, whether text consent is
  checked first.

## Seen across programs

From five programs. A small sample: "seen before", never a norm, never said to the user.

- Consent gated downstream work in all 4 programs that described it. What it blocked varied:
  record or case creation, conversion, welcome materials, or the whole enrollment if unresolved.
- All 5 split consent into separate types.
- 4 of 5 had an e-sign route plus a paper fallback; 1 accepted verbal or written.
- Verbal consent (4 described): accepted with a short validity and a state exclusion; accepted;
  third-party, single call only; not accepted.
- Validity (3 described): from about 30 days for specific consents to 10 years, or until a minor
  turns 18.

## Not the agent's job

The session records how consent works today. It doesn't assess whether the design is correct or
compliant, even when a user volunteers that "consent was implemented incorrectly". That's a
pain point to capture as said, not something to analyse.
