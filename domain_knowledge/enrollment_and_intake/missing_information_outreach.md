---
id: missing_information_outreach
title: Missing information outreach
---

# Missing information outreach (subprocesses)

The same shape of flow runs twice in this process: once to the HCP office (`missing_info_hcp`)
and once to the patient (`missing_info_patient`). Topics: `missing_info.*` on the main flow,
`missing_info_hcp.*` and `missing_info_patient.*` inside each subprocess.

## Shape of the flow

Nearly every program follows the same loop: something is missing, someone is told, outreach is
attempted, attempts are counted, the case escalates or closes at a threshold, and the flow ends
when the item arrives or the case closes. The differences are in the details: who, how often,
how many, to whom it escalates, and when it stops.

A typical structure:

1. Trigger: a task or flag is created, or someone notices.
2. Attempt: a fax, call, text or e-sign link.
3. Gateway: was it received?
4. Loop: if not, the next attempt after an interval.
5. Gateway: has an attempt or time threshold been reached?
6. Escalation: to field staff or a manager (HCP), or through the HCP office or the case owner
   (patient). The loop may continue there.
7. End: information received (return), proceed with partial enrollment (return), or closed.

Attempt counts, intervals and deadlines are usually rules on the loop rather than a separate step
per attempt, unless the user describes attempts that differ in kind (first a fax, then a call,
then a letter).

## Detection is on the main line

How missing items are noticed (a system-generated task, a checklist on the record with no alert,
or a manual review) and how items are routed to the HCP, the patient, or both, are main-flow
topics. The decision that hands work off stays on the main line; the outreach belongs to the
subprocess.

## HCP outreach

- Usually starts by fax, often sent first by the keying role or a vendor, then taken over by the
  case owner. Two teams working the same office in parallel is common (one faxes, the other calls).
- Escalates to field staff or a manager. Field escalation appeared wherever escalation was
  described. Ask how the outcome comes back from the field.
- **The escalation contact may be restricted from seeing patient information.** Field roles are
  sometimes kept away from PHI, so the case owner steps in for anything patient-specific. Worth
  asking what the escalation contact can see and be told.

## Patient outreach

- Usually by phone, plus e-sign links for consent, and texts only where text consent exists.
- Consent is the most common missing item, and often has its own deadline.
- When the patient doesn't respond, programs often go **through the HCP office**: confirming the
  patient's contact details, or asking the office to help reach the patient. That's an escalation
  inside the patient flow, not the start of HCP outreach.
- Unreachable patients often get letters (sometimes with a paper consent form) before closure.

## Endings and closure

The ending is the part users most often leave out: they describe the attempts but not what
happens after the last one. That's the most common source of open questions in this flow.
Closure often needs a **manager's approval**, and several parties are notified (the HCP, field
staff, the vendor, who updates the record). Deadlines are often different for the HCP and patient
paths.

## Automation

Programs increasingly use automation to create tasks, set due dates or call times, or draft
outreach. In none of the programs seen did automation close cases, decide eligibility, or judge
consent validity. If a user describes automation doing one of those, record it as said, and it's
fair to ask once whether anyone reviews it first.

## Seen across programs

From five programs. "Seen before", never a norm, never said to the user.

- Detection (5 described): system-generated task 3, checklist on the record with no alert 2
  (raised as a pain point by both).
- HCP escalation (4 described): field reimbursement 3, manager 1. Trigger: after a number of
  attempts, at a scheduled meeting, or after about two weeks.
- Attempts: HCP 1 to 3 before something changes; patient 2 to 3. Spacing every 1 to 2 days, every
  other business day, or fixed days. Sometimes varying by product, area or region.
- Ending (4 described): fixed deadline then close 2 (roughly two to six weeks), letters then
  close 1, no close rule 1.

## Often left out

- How the person doing outreach finds out it's needed. Some programs have no alert at all.
- What continues in parallel while waiting.
- The ending, and who approves it.
- What the escalation contact can see.
- Variants by product, therapeutic area or region.
