---
id: product_considerations
title: Product considerations
---

# Product considerations

Characteristics of the product, its indication or its patients that change how intake works.
Each is worth recognising when the user mentions it, because it explains branches and rules
that would otherwise look arbitrary.

## Nurse and clinical educator programs

Many programs for injectable or complex therapies offer nurse or clinical educator support:
injection training, onboarding calls, side-effect education. Enrollment into that support varies:

- Opt-in on the enrollment form, or opt-out by default.
- Requires an HCP order or referral.
- Offered at the welcome call, or created automatically at conversion.
- Timed to the first shipment, so training happens when the drug arrives.

A nurse may run a welcome call in parallel with the case owner. Applies when
`program.has_nurse_program` is true.

## Multiple products and formulations

When a program covers more than one product or formulation (for example IV and subcutaneous, or
several strengths), programs usually keep one person record and a separate enrollment record per
product. A patient switching product or formulation follows a distinct path, usually through
duplicate handling. Rules (signature requirements, outreach cadence) sometimes differ by product
or therapeutic area: worth asking when the user mentions more than one product.

## Pediatric populations

If any indication includes patients under 18, consent comes from a parent or guardian, and
something has to happen when the patient turns 18 (new consent, or the record's consent expiring).
Applies when `product.pediatric_population` is true.

## Rare disease and diagnostic confirmation

For rare conditions, the diagnosis may need a genetic or biomarker test to confirm. Some programs
offer free diagnostic testing, sometimes after the patient starts therapy, and define codes that
are ambiguous until the test confirms. This creates extra gateways in eligibility review: see
`../enrollment_and_intake/diagnosis.md`. Small patient populations also mean case owners often know
patients personally, and processes are less automated.

## Titration and starter supply

Products that start at a low dose and step up (titration) sometimes ship a starter supply first.
Programs may route these patients to a quick start or bridge program while coverage is worked.
That program is out of scope for intake, but the hand-off to it is worth capturing.

## Distribution model

- **Limited distribution**: only one or a few specialty pharmacies may dispense, so routing to
  the pharmacy is fixed.
- **Open distribution**: the patient's insurance usually decides the pharmacy, which is decided
  later, in coverage determination.

## REMS

See `rems.md`. Applies when `product.has_rems` is true.
