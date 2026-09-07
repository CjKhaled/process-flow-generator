"""Prompt construction for the extraction call.

The schema itself is supplied to the model as a tool, so the field descriptions in
:mod:`ir.models` already carry the per-field contract. What lives here is the
cross-field reasoning the schema cannot express: which conventions make a graph
*born valid*, so the structural tier passes on the first attempt.
"""

from ir.process_config import ProcessConfig
from ir.skeleton import Skeleton
from validators.report import ValidationReport

_CONVENTIONS = """\
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


def build_system_prompt(config: ProcessConfig, skeleton: Skeleton) -> str:
    """Build the system prompt: the extraction conventions plus this process's vocabulary.

    Args:
        config: Per-process settings supplying the actor vocabulary, the default lane,
            and domain shorthand.
        skeleton: The subprocesses this process is expected to contain.

    Returns:
        The system prompt for the extraction agent.
    """
    sections = [
        (
            f"You extract a structured process graph from a written description of the "
            f"'{config.display_name}' business process, part of a patient support program. "
            f"Return the graph through the supplied schema. Capture what the source says, "
            f"and mark what it leaves open rather than filling the gap yourself."
        ),
        _CONVENTIONS,
        _subprocess_section(skeleton),
    ]
    if config.actors:
        sections.append(_actor_section(config))
    if config.glossary:
        sections.append(_glossary_section(config))
    return "\n\n".join(sections)


def _subprocess_section(skeleton: Skeleton) -> str:
    listed = "\n".join(f"- `{spec.name}` -- {spec.label}" for spec in skeleton.subprocesses)
    return (
        "## Known subprocesses\n\n"
        "These are the only values the `subprocess` field may take. Leave it null for a node "
        "that sits outside all of them.\n\n"
        f"{listed}\n\n"
        "This list is what a complete description usually covers, not a checklist to satisfy. "
        "The source may cover them in a different sequence, and may not mention one at all. "
        "If a subprocess is absent from the text, leave it absent from the graph -- a later "
        "check reports it as an open question. Do not invent steps to fill it in."
    )


def _actor_section(config: ProcessConfig) -> str:
    """The lane vocabulary, with what each one is and where unattributed work goes.

    Rendered in declaration order rather than sorted: ``metadata.yaml`` lists actors in
    roughly the order the process reaches them, which reads better than alphabetical.
    """
    listed = "\n".join(f"- **{actor}** -- {description}" for actor, description in config.actors.items())
    default = (
        f"\n\nWhere the source does not say who performs a step, it is automatic: use `{config.default_actor}`."
        if config.default_actor
        else "\n\nWhere the source does not say who performs a step, use the lane that owns the work it does."
    )
    return (
        "## Swimlanes\n\n"
        "These are the lanes of the diagram, and the only values the `actor` field may take. "
        "Use the names verbatim. What each one is matters: it is how you tell which lane a box "
        "belongs in. If the source attributes a step to someone outside this list, use the "
        f"source's own wording.\n\n{listed}{default}"
    )


def _glossary_section(config: ProcessConfig) -> str:
    listed = "\n".join(f"- **{term}**: {meaning}" for term, meaning in sorted(config.glossary.items()))
    return f"## Domain shorthand\n\nThe source uses these without expanding them. They are not actors.\n\n{listed}"


def build_extraction_prompt(source_text: str) -> str:
    """Build the opening turn: the source text to extract from."""
    return f"Extract the process graph from the description below.\n\n<source>\n{source_text.strip()}\n</source>"


def build_repair_prompt(report: ValidationReport | None, *, schema_error: str | None = None) -> str:
    """Build a repair turn naming the specific defect to fix.

    Only structural defects are fed back. Resolution findings -- a missing
    subprocess, a tagged ambiguity -- are the correct output of this stage, and
    asking the model to "fix" them would invite it to invent content the source
    does not support.

    Args:
        report: The report from the failed attempt, or None if it never parsed.
        schema_error: The SDK's complaint when the response did not fit the schema.

    Returns:
        The next user turn.
    """
    if schema_error is not None:
        return (
            "That response did not fit the schema. The validator reported:\n\n"
            f"{schema_error}\n\n"
            "Return the graph again, correcting that. Do not change the content of the "
            "extraction beyond what the error requires."
        )

    defects = report.structural if report is not None else ()
    listed = "\n".join(f"- {finding.code}: {finding.message}" for finding in defects)
    return (
        "That graph is not structurally valid. These defects must be fixed:\n\n"
        f"{listed}\n\n"
        "Return the corrected graph. Fix only these defects -- keep every other node and edge "
        "as it was. Where a defect exists because the source never states an outcome, close it "
        "with a terminal node marked `status: needs_clarification` rather than inventing what "
        "happens."
    )
