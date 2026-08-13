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


class EdgeType(StrEnum):
    """What kind of connector an edge becomes when the graph is rendered."""

    PRECEDES = "precedes"
    BRANCH = "branch"
    ANNOTATES = "annotates"


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
            "Who performs this step, named from the actor list supplied in the prompt -- for a "
            "gateway, whoever makes the decision. Where the source does not say who, use the "
            "default lane the prompt names. Null only on a terminal or an annotation, which are "
            "not work anyone performs. Never invent an actor outside the supplied list."
        ),
    )
    subprocess: str | None = Field(
        default=None,
        description=(
            "Which known subprocess this node belongs to. Must be one of the subprocess names "
            "supplied in the prompt, or null when the node sits outside all of them."
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
    order: int = Field(
        ge=0,
        description=(
            "Deliberate emission order among the edges leaving the same node, starting at 0. "
            "Used later to lay the diagram out predictably."
        ),
    )


class ProcessGraph(BaseModel):
    """A whole extracted process: the object every later stage consumes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    process_name: str = Field(min_length=1, description="The name of the process, e.g. 'enrollment'.")
    nodes: tuple[Node, ...] = Field(description="Every box in the flow, including annotation nodes.")
    edges: tuple[Edge, ...] = Field(description="Every connector between the nodes above.")
