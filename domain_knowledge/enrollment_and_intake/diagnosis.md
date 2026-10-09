---
id: diagnosis
title: Diagnosis, eligibility and off-label review
---

# Diagnosis, eligibility and off-label review

Covers how a submission is judged eligible, what happens when it isn't (the `off_label_review`
subprocess), and the prescription and prescriber signature. Topics: `eligibility.*`,
`off_label_review.*`, `rx.*`, `hcp_signature.*`.

## Why programs care

Prescribers may legally prescribe off-label. What's restricted is the manufacturer's conduct:
promoting off-label use, and taking steps that turn an off-label prescription into an on-label
claim. Those can expose the manufacturer and its vendors to serious liability. So programs build
intake to read eligibility from what the prescriber wrote, and keep staff away from judging or
shaping diagnoses. That explains rules like "we can't infer the diagnosis from the chart notes"
or "staff can only explain the option if the office asks". See `../agnostic/regulatory.md`.

## Eligibility screening

Criteria seen: diagnosis code (ICD-10), age, a biomarker or test result, product pairing, and a
prescriber attestation that use is on-label. Who judges varies: intake staff against written
rules, the case owner, clinical staff, or a vendor. Criteria often differ by product or
indication.

## What a compliant current state usually looks like

These help the navigator ask precise questions. They are never said to the user, and never
assumed to be true of the user's program.

- Eligibility is read from the form as written.
- Only the prescriber can clarify or change a diagnosis, and the office documents it, usually on
  a new or amended form.
- Clarification outreach is neutral: it asks the office to confirm or clarify, without suggesting
  a code.
- Non-clinical staff don't make clinical judgements.

## Off-label review (subprocess)

### Shape

1. Entry: the eligibility gateway on the main line finds a mismatch or ambiguity. **The gateway
   stays on the main line.** Everything after it, until the patient returns as eligible or exits,
   belongs to the subprocess.
2. A gateway: clearly off-label, or ambiguous? Only where the program defines an ambiguous category.
3. Ambiguous branch: neutral outreach to the prescriber, possibly a diagnostic test offer, and a
   gateway on the prescriber's response or documented judgement.
4. Clearly off-label branch: straight to the program's off-label outcome.
5. Exits: confirmed eligible (back to the main line), routed to an off-label pathway, or closed,
   not enrolled.

### The range of outcomes

Programs disagree on what happens to an off-label patient, and none of the options is the default:

- **Not enrolled.** Closed, with a notice to the HCP and sometimes a call. Sometimes the record is
  never entered, or is archived.
- **Routed elsewhere.** For example to a specialty pharmacy, so the patient can still get drug
  outside the program's services.
- **A separate account type.** The patient is recorded and may get limited services.
- **Case-by-case review.**

### Ambiguous codes, testing and prescriber judgement

Some programs define codes that aren't clearly on- or off-label. These trigger a call to the
prescriber, sometimes an offer of diagnostic testing (in rare disease, sometimes free and
sometimes after therapy starts), and sometimes allow a documented clinical judgement from the
prescriber to satisfy the criteria. Each of these is a gateway with its own outcomes, and users
often describe them as a nested chain of "if… then if…".

### Listening carefully

Users sometimes describe practices like "we work with the office to get the right code", "we tell
the prescriber which code to select", or "we convert off-label to on-label". The session's job is
to record what actually happens. Ask neutrally what the steps are: who contacts whom, what is
asked, whether it's proactive or only on request, and how the answer comes back. Capture the
answer in the user's words. Don't characterise it, don't advise, and don't suggest a compliant
alternative. If the team wants such practices reviewed, that happens outside the conversation.

## Prescription

Programs disagree sharply here: a prescription required before enrollment (entered exactly as
written), not required with the patient left pending, not required and sent to the pharmacy
later, or its arrival upgrading a partial enrollment. Always ask.

## HCP signature and attestation

When the prescriber's signature or attestation is missing, it may block enrollment, block welcome
outreach, be followed up in parallel, or vary by therapeutic area.

## Seen across programs

From five programs. "Seen before", never a norm, never said to the user.

- Criteria (3 described): diagnosis code 3, age 3, biomarker or test 2, product pairing 1,
  prescriber attestation 1.
- Eligibility read from the form only: all 3 that described it. Non-clinical staff make no
  clinical judgement: 4.
- Off-label outcome (3 described): closure notice 1, routed to specialty pharmacy 1, separate
  account 1. No consensus: always ask, never assume closure.
- A defined ambiguous-code list with testing and prescriber-judgement override: 1 of 3.
- Prescription requirement (4 described): four different answers.
- HCP signature (2 described): blocks welcome outreach 1, varies by therapeutic area 1.

## Often left out

- How a corrected diagnosis comes back: a new form, an amended form, or a phone note. This decides
  whether the patient re-enters at intake or continues where they were.
- Who is told about the outcome, and how.
- What happens if the same patient later returns with an on-label submission.
- What happens after diagnostic testing disproves the diagnosis.
