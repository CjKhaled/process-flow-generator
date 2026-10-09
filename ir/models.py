"""The typed process graph.

This module is the single source of truth for the whole project. It is at once:

* the structured-output target the extractor asks the LLM to fill in,
* the object the validator checks, and
* the contract later stages (layout, BPMN rendering) consume.

Because Strands renders these models into the tool schema the model actually sees,
**every field description here is prompt text**. Editing a description changes
extraction behaviour, so treat them as carefully as the types.

The models are deliberately *shape-only*: they enforce field types and trivial
non-emptiness, and nothing else. Graph semantics -- unique ids, edges pointing at
real nodes, gateway arity, reachability -- live in ``validators/``. Two reasons:

1. The validator's tests must be able to construct a broken graph (a dangling
   gateway, a dangling edge reference) in order to assert the validator catches
   it. That is impossible if the model rejects it first.
2. Keeping semantics in one place means later stages inherit the guarantee from
   the validator rather than accidentally re-running checks via the model.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NodeType(StrEnum):
    """What kind of box a node becomes when the graph is rendered."""

    START = "start"
    TASK = "task"
    GATEWAY = "gateway"
    TERMINAL = "terminal"
    SUBPROCESS = "subprocess"
    ANNOTATION = "annotation"


class NodeStatus(StrEnum):
    """Whether the source settles this node, or a human still must.

    Deliberately binary. A middle value for "follows from what the source says"
    invites the model to fill gaps from how these processes usually run, and
    nothing downstream can tell such a node from a stated one. Anything the source
    does not settle is an open question, which is the output of this stage.
    """

    STATED = "stated"
    NEEDS_CLARIFICATION = "needs_clarification"


class NodeOrigin(StrEnum):
    """Where a node came from: the user's words, a convention, or the slicer.

    Separate from :class:`NodeStatus`, which stays binary. Status says whether a
    human still has to settle the node; origin says who put it there. Whether a
    node rests on the first description or on a later answer is not recorded here
    either -- it is read off the statements its evidence cites.
    """

    SOURCE = "source"
    """Supported by statements the user made."""

    RULE = "rule"
    """Created by a convention: the terminal closing an outcome the user never stated."""

    SLICE = "slice"
    """Synthesised by code when a subprocess is cut out as a flow of its own."""


class EdgeType(StrEnum):
    """What kind of connector an edge becomes when the graph is rendered."""

    PRECEDES = "precedes"
    BRANCH = "branch"
    ANNOTATES = "annotates"


class BranchAnswer(StrEnum):
    """Which answer a branch of a yes/no decision represents."""

    YES = "yes"
    NO = "no"


class EvidenceRef(BaseModel):
    """One piece of support for a node or a branch: a statement, and the words in it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: str = Field(
        min_length=1,
        description=(
            "The id of the numbered statement this rests on, exactly as the prompt lists it, "
            "e.g. 's_0007'. Only ids the prompt supplies; never one you have made up."
        ),
    )
    quote: str = Field(
        min_length=1,
        description=(
            "The words in that statement which support this, copied exactly from the "
            "statement's text or from its restatement -- character for character, with nothing "
            "added, dropped, reordered or paraphrased. Keep it to the clause that carries the "
            "support rather than the whole statement. A quote that cannot be found in the "
            "statement it cites is rejected."
        ),
    )


class Node(BaseModel):
    """A single box in the process flow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(
        min_length=1,
        description=(
            "Stable, unique, human-readable identifier in snake_case, e.g. "
            "'submit_pef' or 'gw_is_off_label'. Referenced by every edge."
        ),
    )
    type: NodeType = Field(
        description=(
            "start: the single entry point. task: one unit of work performed by an actor. "
            "gateway: a decision with two or more outgoing branches. terminal: an end state. "
            "subprocess: one collapsed box standing for a whole named subprocess -- never "
            "expand it into its own nodes. annotation: a business rule or record value that "
            "describes another box rather than sitting in the flow."
        )
    )
    label: str = Field(
        min_length=1,
        description="Short imperative phrase shown inside the box, e.g. 'Transcribe PEF into CRM'.",
    )
    actor: str | None = Field(
        default=None,
        description=(
            "The swimlane this box is drawn in, named from the actor list supplied in the "
            "prompt. Required on every node, whatever its type. Work takes the lane of whoever "
            "performs it, and a gateway the lane of whoever decides. A terminal takes the lane "
            "that owns the outcome, which is often not the lane of the box pointing at it. An "
            "annotation takes the lane of the box it describes. Where the source names nobody, "
            "use the default lane the prompt gives. Never invent one outside the supplied list."
        ),
    )
    subprocess: str | None = Field(
        default=None,
        description=(
            "Which known subprocess this node belongs to -- set only on work the source hands "
            "off down a named path, such as the branch leaving 'if it is off-label'. The "
            "deciding gateway itself stays on the main line, and so does the running narrative: "
            "both leave this null. Must be one of the subprocess names supplied in the prompt. "
            "A later stage draws each tagged subprocess as one collapsed box."
        ),
    )
    status: NodeStatus = Field(
        description=(
            "stated: the source supports this, whether it says so directly or through plain "
            "sequencing. needs_clarification: the source does not settle this and a human must, "
            "in which case 'detail' has to say what is open. If settling the question would need "
            "knowledge the source does not contain, it is needs_clarification, never stated."
        )
    )
    detail: str | None = Field(
        default=None,
        description=(
            "The supporting source text -- ideally a direct quote. For a node collapsing "
            "several channels or outcomes, record all of them here. Required on a "
            "needs_clarification node, where it must say what the source leaves open."
        ),
    )
    alternatives: tuple[str, ...] = Field(
        default=(),
        description=(
            "Competing outcomes the source lists without giving any rule for choosing between "
            "them, e.g. ('not entered into the CRM', 'archived'). Use this instead of inventing "
            "a gateway with conditions the source never states. Empty when there is no such "
            "ambiguity."
        ),
    )
    evidence: tuple[EvidenceRef, ...] = Field(
        default=(),
        description=(
            "The statements this node comes from. Used only when the prompt supplies numbered "
            "statements; leave it empty when it supplies plain source text. Cite every statement "
            "that supports the node, not just the first, each with its own exact quote. Required "
            "on every node whose origin is 'source'. Empty on a node whose origin is 'rule', "
            "since by definition nothing the user said supports it."
        ),
    )
    origin: NodeOrigin = Field(
        default=NodeOrigin.SOURCE,
        description=(
            "source: the user's statements support this node -- the ordinary case, and the "
            "default. rule: this node exists only because a convention requires it, and that is "
            "only ever the needs_clarification terminal closing an outcome the user did not "
            "state; never use it for a task, a gateway, or a terminal the user described. "
            "slice: reserved for code; never emit it."
        ),
    )


class Edge(BaseModel):
    """A single connector between two nodes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_id: str = Field(min_length=1, description="The id of the node this edge leaves.")
    to_id: str = Field(min_length=1, description="The id of the node this edge enters.")
    type: EdgeType = Field(
        description=(
            "precedes: plain sequence flow. branch: one labelled outcome leaving a gateway; "
            "every branch edge needs a condition. annotates: a dashed connector running from "
            "an annotation node to the box it describes."
        )
    )
    condition: str | None = Field(
        default=None,
        description=(
            "The guard on a branch edge, phrased as the source phrases it. Keep a combined "
            "condition whole -- 'patient is 18 or older AND the diagnosis code is in the "
            "document' is one condition, not two. Null on precedes and annotates edges."
        ),
    )
    answer: BranchAnswer | None = Field(
        default=None,
        description=(
            "On a branch leaving a gateway that asks a yes/no question, which answer this "
            "branch is: 'yes' or 'no'. The diagram draws that word on the arrow, which is why "
            "it is worth setting even though `condition` says the same thing at length -- the "
            "wording stays in the graph without crowding the drawing. Leave null when the "
            "decision is not a yes/no question, such as one with three outcomes or a choice "
            "between named alternatives; the condition is drawn instead. Null on precedes and "
            "annotates edges."
        ),
    )
    order: int = Field(
        ge=0,
        description=(
            "Deliberate emission order among the edges leaving the same node, starting at 0. "
            "Used later to lay the diagram out predictably."
        ),
    )
    evidence: tuple[EvidenceRef, ...] = Field(
        default=(),
        description=(
            "The statements this branch comes from, each with an exact quote. Used only when "
            "the prompt supplies numbered statements. Required on every branch edge, because a "
            "branch is a claim about what the process does under a condition -- with one "
            "exception: a branch leading to a terminal whose origin is 'rule' carries none, "
            "since the user never stated that outcome. Leave empty on precedes and annotates "
            "edges."
        ),
    )


class ProcessGraph(BaseModel):
    """A whole extracted process: the object every later stage consumes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    process_name: str = Field(min_length=1, description="The name of the process, e.g. 'enrollment'.")
    nodes: tuple[Node, ...] = Field(description="Every box in the flow, including annotation nodes.")
    edges: tuple[Edge, ...] = Field(description="Every connector between the nodes above.")
