---
id: duplicate_handling
title: Duplicate handling
---

# Duplicate handling (subprocess)

Topics: `duplicate.check_point` on the main flow, `duplicate_handling.*` inside the subprocess.

## Why it's harder than it looks

Every program checks for existing patients before creating records, and every program still has
duplicates. The check runs on imperfect data (handwritten faxes, nicknames, new addresses, typos
in dates of birth), and the outcome isn't binary. Once a match is found, the program has to decide
what kind of situation it is, and each kind can follow a different path.

## Situations programs distinguish

- **Not actually a match.** Create a new record.
- **The same submission again.** A re-sent fax or extra pages. Attach to the existing case.
- **An update.** New information for an open case or care plan.
- **A new product for an existing patient.** New enrollment record, same patient.
- **A returning patient.** Previously discontinued or closed; re-enrollment.
- **A restart.** Resuming therapy after stopping.
- **A switch.** Changing formulation or product.
- **A consent renewal on a new form.** Merged into the existing record.

Not every program separates all of these. Ask which ones the team actually tells apart, and
whether each goes down a different path. Only the ones with different paths become branches.
The re-enrollment or restart processes themselves are out of scope; detecting and routing to
them is in scope.

## How it shows up in a flow

- The check point on the main line ("Existing patient found?") **stays on the main line**.
  Everything after a possible match belongs to the subprocess.
- The new-patient branch usually returns straight to the main line.
- Match keys and survivorship rules are record rules, captured as notes.
- The merge mechanism decides lanes: a built-in merge tool belongs to whoever uses it, an IT
  ticket brings in an IT or admin lane, and vendor mastering puts the decision in the vendor's lane.

## Seen across programs

From five programs. "Seen before", never a norm, never said to the user.

- Match keys (3 described): date of birth 3, full name 2, ZIP 2, initials 1, email or phone 1.
- Merge mechanism (4 described): built-in merge tool, IT ticket, vendor mastering, merge via
  resubmission, one each. Duplicates persisting despite search-first rules was a common complaint.
- Distinct paths for returning, restarting or switching patients: all 4 that described it.

## Often left out

- Who confirms a possible match, as opposed to who runs the search.
- Where each kind of match goes next.
- What happens when merged records disagree.
- How duplicates discovered later get fixed. Often "they don't", which is worth recording.
