"""The conventions that make a graph *born valid*.

The schema is supplied to the model as a tool, so the field descriptions in
:mod:`ir.models` already carry the per-field contract. What lives here is the
cross-field reasoning a schema cannot express: one start, every gateway with two
conditioned branches, every path reaching a terminal, what is a subprocess and
what is not, what an annotation is for. A patch that follows them passes the
structural tier on the first attempt.

They are the patch extractor's, joined into its system prompt by
:func:`agents.extractor.build_system_prompt`. "The source" throughout means the
user's numbered statements; the prompt says so before quoting this block.
"""

CONVENTIONS = """\
## How to build the graph

The graph is flat. Never nest one graph inside another.

**One start.** Emit exactly one node of type `start`, even when the source names
several ways in for the same request (a portal, a fax, a phone call). Name the
channels in that node's `label` and `detail`. Separate start nodes for separate
channels produce a diagram that reads as several unrelated processes.

**A subprocess is work the source hands off.** A subprocess begins where a
decision sends the process down a named path -- "if it is off-label, the
off-label process begins" -- or where the document gives a stretch of text its
own heading. Tag every node on that path with the subprocess it belongs to, and
keep tagging until the path rejoins the main line.

The decision itself is *not* part of what it hands off: the gateway stays on the
main line with `subprocess` null, and only the branch leaving it is tagged. Steps
in the running narrative -- the ones the source describes without handing them
off to anything -- leave `subprocess` null too. If in doubt, ask whether the
source treats the work as a named thing that happens rather than as the next
sentence; only the first is a subprocess.

Tagging is still flat: emit the tagged steps as ordinary `task` and `gateway`
nodes with a tag, never as a graph nested inside another. Reserve the
`subprocess` node *type* for a subprocess the source names but does not detail at
all -- one box standing in for work described nowhere.

A later stage draws every tagged subprocess as a single collapsed box, so the
steps you tag will not appear individually in the diagram. Extract them in full
regardless: they are what the open questions are found in.

**Every gateway gets at least two conditioned branches.** Sources routinely give
only the happy path: "if the prescriber agrees, the patient proceeds", with
nothing about disagreeing. Do not leave that gateway with one branch, and do not
invent what happens instead. Emit the other branch, give it the condition implied
by the text ("prescriber does not agree"), point it at a `terminal` node, and mark
that terminal `status: needs_clarification` with a `detail` saying the source does
not state this outcome. A dangling gateway is rejected; a tagged open question is
exactly what this stage is for.

**Say which branch is the yes.** Most gateways ask a yes/no question -- "is the
diagnosis code off-label?", "does the patient already exist?". On each branch of
one, set `answer` to `yes` or `no`, and still fill in `condition` with the
source's own wording. The diagram draws the answer on the arrow and keeps the
wording in the graph, so a reader sees a decision and its two outcomes rather
than a sentence hanging off a line. Where the decision is not a yes/no question
-- three outcomes, or a choice between named alternatives such as DocuSign,
paper or verbal -- leave `answer` null on every branch and the condition is drawn
instead.

**Every path reaches a terminal.** No node may be a dead end. Loops back to an
earlier step are fine as long as some route out of the loop reaches a terminal.

**Keep a combined condition whole.** "patient is 18 or older AND the diagnosis
code is in the document" is one condition on one branch. Splitting it into two
gateways invents a decision sequence the source never describes.

**Competing outcomes with no rule go in `alternatives`.** When the source lists
outcomes without saying which applies -- "they either won't be entered into the
CRM or will just be archived" -- put both strings in `alternatives` on a single
node. Do not build a gateway whose conditions you had to make up.

**Business rules and record values are annotations.** A status, a substatus, a
field value, a policy statement -- these describe a step, they are not a step.
Emit an `annotation` node holding the rule and join it to the box it describes
with an `annotates` edge. Never model a record value as a `task`, and never wire
an annotation into the sequence flow.

**Every box sits in a swimlane.** `actor` is the lane the box is drawn in, and no node
may be left without one -- not a terminal, not an annotation. Choose it like this:

- A `start`, `task` or `gateway` takes the lane of whoever performs it; for a gateway,
  whoever makes the decision.
- A `terminal` takes the lane that **owns the outcome**, which is often not the lane of
  the box pointing at it. "HCP works directly with SP Biologics" is the HCP lane even
  when the preceding step was someone else's, and an enrolment that ends unresolved sits
  with whoever owns enrolment, not with whoever happened to ask the last question.
- An `annotation` takes the lane of the box it describes.
- Where the source names nobody -- usually the passive voice, "is assigned",
  "automatically creates" -- the step is automatic and goes to the default lane named
  below.

**Be honest about status.** There are two labels and no middle ground. `stated`
is for what the source supports: what it says outright, and the plain sequencing
it implies ("then", "from there"). `needs_clarification` is for everything the
source leaves open, and its `detail` must say what is missing. The dividing line
is whether settling the question needs knowledge the source does not contain --
filling a gap from how these processes usually run is never `stated`. Guessing
and marking it `stated` is the one failure this stage cannot recover from.

**Ids and ordering.** Node ids are unique and snake_case. On edges leaving the
same node, set `order` to the sequence you want them read in, starting at 0.
"""
