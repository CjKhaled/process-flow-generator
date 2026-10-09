---
id: regulatory
title: Regulatory foundations
---

# Regulatory foundations

This file explains why patient support processes look the way they do, so the navigator
understands what it hears. It's a general orientation, not legal advice, and the session never
assesses whether a program's process is compliant.

## HIPAA

Governs how health information is shared and used. Because manufacturers and hubs generally
aren't the patient's provider, programs rely on a patient authorization that names what is
shared, with whom, for what purpose, and until when, with a right to revoke.

Shows up as: the HIPAA authorization as the master gate, separate consent types, expiry dates,
questions about what can be done with a lead's data before consent arrives, and **roles that
may not see health information** (some field roles are kept away from PHI, so work gets routed
around them). See `consent.md`.

## Anti-Kickback Statute and beneficiary inducement rules

Restrict giving anything of value that could induce use of a product reimbursed by government
programs. Shows up as: eligibility for some services tied to insurance type, and programs
avoiding anything that could look like steering a patient's insurance choices. Mostly relevant
to coverage determination and financial assistance, but it explains why intake sometimes records
insurance type early.

## FDA promotional rules

Manufacturer communications must be consistent with the approved label. Shows up as: eligibility
read strictly from on-label criteria, approved scripts for staff, and off-label outcomes routed
outside normal program services. See `../enrollment_and_intake/diagnosis.md`.

## False Claims Act

Creates liability for causing false claims to government payers. Shows up as: strict separation
between what the prescriber decides and what program staff do, especially around diagnosis codes.

## REMS

FDA-required safety programs for certain drugs. See `rems.md`.

## Telephone Consumer Protection Act

Governs consent for texts and automated calls. Shows up as: a separate text-messaging consent,
opt-out handling, and text outreach in missing-information flows depending on that consent.

## Electronic signature laws

Federal and state laws make electronic signatures valid when done properly. Shows up as: e-sign
platforms with audit trails as the primary consent route.

## State laws

Vary on minors' consent, consumer health data, verbal consent and call recording. Shows up as:
state exclusions (for example, verbal consent not accepted for residents of a particular state),
and different handling for minors.

## Non-US patients

Programs serving patients outside the US follow other countries' rules. Shows up as: separate
forms, cadences or attempt limits by region.

## What the navigator does with this

Uses it to recognise why a rule exists and to ask a better follow-up. For example, if a user says
texts go out for missing information, asking whether text consent is checked first is
reasonable, asked once and openly. It never tells the user a rule applies to them, never comments
on compliance, and never suggests changes.
