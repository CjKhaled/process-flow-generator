# Technical reference

What actually happens, stage by stage, at the level of files and functions. Read the
[README](README.md) first if you want the plain-language version — this document assumes you
want the detail.

Three stages. Only the first one calls a model; stages 2 and 3 are deterministic, and the
same input always produces byte-identical output. Stage 1 is a conversation, and it is where
almost all of the moving parts are.

---

# Stage 1 — the conversation

```
description ─► split into statements                              session.json
                    │                                             (rewritten after
                    ▼                                              every turn)
 ┌─► 1 interpreter ─► 2 apply ─► 3 extractor ─► 4 record ─► 5 rank ─► 6 navigator ─► 7 store
 │      (agent)       (code)     patch+repair    (code)     (code)     (agent)       (code)
 │                                  (agent)
 └──────────────────────────── the user's answer ◄───────────────────────────────────┘

 accept ─► freeze the graph ─► slice each subprocess ─► per-flow folder ─► stages 2 and 3
```

A validated `ProcessGraph`, reached over as many turns as the user cares to take. After
every reply the pipeline stops and waits for a person; nothing runs between turns.

| | |
| --- | --- |
| Entry points | `session/cli.py` · `POST /sessions` in `api/sessions.py` |
| Pipeline | `session/orchestrator.py::run_turn` — both entry points call it |
| LLM calls per turn | Up to three agents; the extractor may repeat |
| State | One `Session`, in `sessions/<id>/session.json` |
| Knowledge | `domain_knowledge/`, read-only, through `knowledge/` |

**Why plain code and not an agent framework's control flow.** A session is a long loop that
stops for a person between every turn, with state that has to be inspectable and replayable.
Inside one turn the work is fixed and sequential. So there are three narrow Strands agents,
each answering in a Pydantic schema, called in order by ordinary Python — no swarm, no graph,
no agent-as-tool. Strands' human-in-the-loop interrupts pause an agent *inside* its own tool
loop; here the pause is *between* turns, every agent call runs to completion, and nothing
needs resuming. For the same reason no Strands session manager is attached: the agents are
built fresh each turn and have no state of their own to persist.

## 1A. The knowledge base and who reads it

`domain_knowledge/agnostic/` holds `personas.yaml`, `glossary.yaml` and markdown that applies
to any process. `domain_knowledge/<process>/` holds `process.yaml`, `checklist.yaml` and that
process's topic files. `knowledge/schemas.py` models each YAML file with `extra="forbid"`, so
a misspelt key is a load failure. `load_domain(process_id)` returns the parsed files and
every markdown body — agnostic first, then the process folder, sorted by path — cached per
process.

`knowledge/compose.py` is where access is decided:

| Agent | Sees | Does not see |
| --- | --- | --- |
| Navigator | Every markdown file in full, the whole checklist, the process definition | — |
| Interpreter | Open topics as id, title and cues; glossary; personas; subprocess ids; unknown facts | Topic questions, markdown |
| Extractor | Session lanes with descriptions, the default lane, glossary, subprocess ids | The checklist, every markdown file, anything about other programs |

The extractor's row is the rule the feature is built on. A step that came from the knowledge
base would be indistinguishable from one the user stated, so the agent that writes the graph
is given vocabulary and nothing else. `tests/test_knowledge_compose.py` asserts its view
contains no checklist question and no markdown.

`tests/test_domain_knowledge.py` checks what the files must agree on between themselves:
unique topic ids, scopes that exist, `leads_to` targets that exist, every subprocess reached
by some topic, exactly one screening topic per program fact, every persona referenced
defined, every markdown path mentioned in a body resolving.

**The four program facts** — `product.has_rems`, `program.has_nurse_program`,
`program.patient_self_enrollment`, `product.pediatric_population` — switch topics off. A fact
is unknown until the user states it, and an unknown fact never filters.

## 1B. What was added to the IR

All optional with defaults, so every graph already on disk still parses and stage 2 is
undisturbed:

| Field | Meaning |
| --- | --- |
| `Node.evidence`, `Edge.evidence` | `EvidenceRef(statement_id, quote)` — the statements this came from and the exact words in them |
| `Node.origin` | `source` (the user's statements support it) · `rule` (the terminal closing an outcome nobody stated) · `slice` (synthesised when a subprocess is cut out) |

`NodeStatus` stays binary. Whether a node rests on the first description or on a later answer
is read off the statements its evidence cites, not stored on the node.

## 1C. The session file

`session/models.py::Session`, versioned by `schema_version`. The records inside are frozen;
the session is not, and a turn works on a deep copy that replaces the original only if the
turn succeeds.

| Field | Holds |
| --- | --- |
| `phase` | `describing` · `probing` · `closing` · `complete` · `abandoned` |
| `focus`, `requested_focus` | `main` or a subprocess id; and a scope the user opened in the page, honoured next turn |
| `turn`, `turn_status`, `turn_error` | The turn counter, what the turn in flight is doing, and the sentence for a failed one |
| `corpus` | Every `Statement`: id (`s_0001`…), origin, turn, raw text, optional restatement, the question it answered, topics, scope |
| `transcript` | Each line said, with the questions shown under an assistant line |
| `lanes`, `default_lane` | `SessionLane`: name, persona, description, evidence, `placeholder` · `proposed` · `confirmed` |
| `glossary`, `unknown_terms` | Terms the user explained; terms they used without explaining |
| `facts` | The four program facts, each `true`, `false` or unknown |
| `graph` | The master graph. The only graph a session has |
| `versions` | Per turn: the patch, whether it was applied, attempts, findings, and the duration of every step |
| `ledger` | One `LedgerEntry` per checklist topic |
| `pending` | The questions the user was last asked |
| `retry_statement_ids` | Statements a failed extraction still owes |
| `accepted_open_items` | What the user accepted as open at close-out |

`FileSessionStore` writes to a temporary file in the same folder and renames it into place,
so the page, which polls while a turn runs, never reads half a session. Session ids and flow
names become folder names and arrive from URLs, so both are matched against
`[A-Za-z0-9_-]{1,64}` before any path is built.

**Lanes.** A session starts with one lane, `System (unconfirmed)`, in the process's default
persona. It is where unattributed work goes until the user names the system that does it.
When a lane in that persona is learned, or the user answers the default-lane question, every
node in the placeholder moves to the named lane and the placeholder is dropped. A lane the
interpreter proposes is usable at once — the extractor needs somewhere to put work the user
has already attributed.

## 1D. The model seam

`extractors/conversation.py` is what the agents depend on, and it imports no SDK:

| Protocol | Method |
| --- | --- |
| `ConversationFactory` | `open(role, system_prompt, cached_context=None) -> StructuredConversation` |
| `StructuredConversation` | `send(prompt, output: type[T]) -> T` |

`extractors/model.py` implements both with Strands and is the only file that imports it. The
schema is handed to the model as a **tool** (`structured_output_model=`), not requested in
prose, so there is no parser to write for the ways a model can be slightly wrong. No
temperature or top-p is set: current Claude models reject them.

**The retry taxonomy** lives in the exception translation, and it is the whole of the
distinction:

| SDK failure | Becomes | Effect |
| --- | --- | --- |
| `StructuredOutputException` | `SchemaCallError` | Retry, quoting the complaint |
| `MaxTokensReachedException` | `SchemaCallError` | Retry — the graph was cut off mid-generation |
| `APIStatusError` | `ModelUnavailableError` | **Abort immediately.** No repair prompt fixes a bad key, a bad model id, or a quota |
 The model per role comes from `PFG_INTERPRETER_MODEL_ID`,
`PFG_EXTRACTOR_MODEL_ID` and `PFG_NAVIGATOR_MODEL_ID`, each falling back to `PFG_MODEL_ID`.

**Caching.** `cached_context` is sent as the opening exchange of the conversation, ending in a
cache point, not as part of the system prompt. Strands' Anthropic provider sends the system
prompt as a plain string, which drops a cache point placed there; one inside a message is
honoured. The navigator's knowledge is the same text on every turn of every session about a
process, so it is the block this exists for.

## 1E. The interpreter

*What did the user just say, in relation to what was asked?* One fresh conversation per turn.
It never sees the graph.

| | |
| --- | --- |
| Reads | The message — or on turn 1 the description's statements — pending questions with their topics and steps, open topics, glossary, lanes, personas, subprocess ids, unknown facts, unknown terms, focus |
| Returns | `InterpretResult`: statements, topic updates, corrections, new lanes, lane updates, the default lane, learned and unknown terms, facts, a focus request, `meta` |
| Failure | One repair turn for a schema slip, then the turn is rejected with no state change |

On turn 1 the description is split by `session/statements.py` — each non-empty line, then
sentences within a line, deterministically — and the interpreter classifies those statements
by number. Code does the splitting because statement text is what quotes are checked against,
and a model asked to split is also free to tidy. On later turns the interpreter splits the
message itself, and any statement whose text is not found in the message is replaced by the
whole message.

Its rules are in `agents/prompts/interpreter.md`. The ones that matter most: a restatement
may contain only what the answer states or affirms; silence is not absence;
`confirmed_absent` needs the user to say so; a form, a task or a status is never a lane; an
unexplained term is reported, never guessed.

Its output is a *reading*. Every change it implies is applied by code, which drops what does
not hold up — a persona that does not exist, a topic not in the checklist.

## 1F. The extractor, and patches

*Turn new statements into graph changes. Nothing else.*

| | |
| --- | --- |
| Reads | The master graph as JSON, every statement with this turn's marked `NEW` and owed ones `RETRY`, this turn's corrections |
| System prompt | `extractor_patch.md` + the conventions block from `extractors/prompt.py` + `extractor_context` |
| Returns | `GraphPatch`: a list of operations |
| Conversation | Held across repair attempts within a turn, never across turns |

It returns a patch, not a graph, for two reasons: node ids stay stable, which topics, pending
questions and the page's open rationale are all keyed by; and an answer changes little, so
asking for the whole graph again would invite revisions nobody asked for. Turn 1 is a patch
against an empty graph, so there is one path.

| Operation | Fields |
| --- | --- |
| `add_node` | `node` |
| `update_node` | `id`, `fields` — a partial node |
| `remove_node` | `id`, `reason_statement_ids`. Its edges go with it |
| `add_edge` | `edge` |
| `update_edge` | `from_id`, `to_id`, `order`, `fields` — a partial edge, which may re-point it |
| `remove_edge` | `from_id`, `to_id`, `order`, `reason_statement_ids` |

In a partial node or edge, null means *unchanged*, because a model writes explicit nulls for
fields it has no view on; a `clear` list names the few fields that can be emptied.
`apply_patch` is pure and never raises on a bad operation: it skips it and reports it, so the
repair turn can name everything wrong with a patch at once. Nodes a patch adds are moved to
just after the step that leads to them, because stage 2 lays out by node order and a patch
can only append.

### The conventions

The schema carries per-field meaning. `extractors/prompt.py::CONVENTIONS` carries what a
schema cannot express — rules that span several fields or several objects. Together they aim
at a patch that leaves the graph *born valid*, so the structural tier passes on the first
attempt. "The source" in that block means the user's numbered statements.

| Group | Rules |
| --- | --- |
| **Graph shape** | The graph is flat, never nested. Exactly one `start`, even where the source names several intake channels — those go in that node's label and detail. Every path reaches a terminal; loops are fine as long as some route out reaches one |
| **Decisions** | Every gateway gets at least two branches, each carrying a condition. Where the source gives only the happy path, emit the other branch, point it at a terminal, and mark that terminal `needs_clarification` — do not invent the outcome. Set `answer` to yes or no on each branch of a yes/no question, and still fill in `condition`. Keep a combined condition whole: *"18 or older AND the code is in the document"* is one condition, not two gateways |
| **Subprocess tagging** | A subprocess is work the source **hands off** at a decision, or a stretch the document gives its own heading. Tag every node on that path until it rejoins the main line. **The deciding gateway itself stays on the main line**, untagged, and so does the running narrative. Tagging stays flat — tagged steps are ordinary tasks and gateways with a tag, never a nested graph |
| **Honesty** | Two statuses and no middle ground. Competing outcomes with no stated rule go in `alternatives`, not into an invented gateway. Business rules and record values are annotations, never tasks, and never wired into the sequence flow |
| **Swimlanes** | Every box sits in one. A start, task or gateway takes the lane of whoever performs or decides. A **terminal takes the lane that owns the outcome**, which is often not the lane of the box pointing at it. An annotation takes the lane of the box it describes. Where nobody is named, the default lane |
| **Ids and order** | Unique snake_case ids. On edges leaving the same node, `order` starts at 0 and sets the sequence they are read in |

### The checks, and the 7 session codes

After a patch is applied, `agents/extractor.py::check` runs two validators.
`validate(graph, skeleton)` judges the graph by itself and is described in the next section.
`validators/session_checks.py::validate_session(graph, corpus, lanes, process)` judges it
against the session: the statements, the process definition. Its seven codes are all
structural.

| Code | Fires when |
| --- | --- |
| `missing_evidence` | A `source` node, or a branch edge, cites nothing. Exempt: the branch leading to a `rule` terminal — nobody stated that outcome, so there is nothing to quote |
| `evidence_not_found` | A reference names a statement that does not exist, or its quote is not in that statement's text or restatement. Compared with case, whitespace and typographic quotes normalised. Also raised for a removal citing an unknown statement |
| `unknown_scope` | A node's `subprocess` is not declared in `process.yaml` |
| `rule_origin_misuse` | An `origin: rule` node that is not a `needs_clarification` terminal, or any node with `origin: slice` |
| `patch_unknown_node` | `update_node` or `remove_node` names a node that is not there |
| `patch_duplicate_node` | `add_node` uses an id already taken |
| `patch_unknown_edge` | `update_edge` or `remove_edge` names an edge that is not there. An edge is found by its ends alone when exactly one joins them, since the order is what a model misremembers |

**There is no lane check.** A lane the extractor uses that the session has not learned is
accepted, and `session/orchestrator.py::learn_lanes` adds it as `proposed` with no persona —
the state the candidates turn into a rank 2 question, "what is X, and what part does it
play?". It is far more often a name the user said and the interpreter missed than an
invention, and either way the right response is to ask, not to send the patch back.

`evidence_not_found` is what makes extraction literal. A paraphrase is not a quote, and a
node that rests on a paraphrase is sent back.

### The repair loop

| Attempt outcome | Next |
| --- | --- |
| `SchemaCallError` | Validation is skipped. The repair turn quotes the SDK's complaint and says to correct that and change nothing else |
| Structurally invalid | The repair turn lists `code: message` for each structural finding |
| Structurally valid | The graph is accepted, with its resolution findings |

Only structural findings are ever fed back, in the held conversation, with "fix only these
defects; keep every other node and edge". Each repair is a whole corrected patch against the
*original* graph — a rejected patch was never applied. Budget is
`PFG_MAX_EXTRACTION_ATTEMPTS`, first attempt included.

Running out of attempts is an outcome, not an error. A session always has last turn's graph,
which is valid: the graph is kept, the turn's statements go to `retry_statement_ids`, the next
turn's prompt marks them `RETRY`, and the page says the flow was not updated.

The extractor is not called at all when a turn described nothing — a quick reply, or a
message about the session itself — unless statements are owed or something was corrected.

## 1G. The graph validator

`validate(graph, skeleton)` is a pure function — it returns findings and never touches the
graph.

**`flow_view` first.** The graph is projected onto its control-flow subgraph: annotation
nodes and `annotates` edges removed, adjacency built once for the predicates to share.
Without this, a well-formed graph looks full of orphans and dead ends, because annotations
carry no sequence flow.

**Check order is load-bearing.** `duplicate_node_id` and `dangling_edge_ref` run first. If
either fires, **every flow predicate is skipped**. They index nodes by id and follow edges
between them, so on a graph with duplicate ids or dangling references they produce noise
rather than signal.

### Why a validator at all, when structured output exists

Structured output guarantees each `Node` and `Edge` **in isolation**: correct types,
non-empty strings, valid enum members, `order >= 0`, no extra fields. Pydantic validates one
object at a time and never sees the others.

Every structural check is a claim about **how objects relate**. Of the ten below, eight are
flatly impossible in a per-object schema. The other two could be schema rules and are
deliberately not: `actor` is typed `str | None` on purpose, because `ir/models.py` is kept
shape-only so the validator's own tests can construct broken graphs to prove the checks fire.
Make the model reject them and those tests cannot be written.

Three layers, each doing something the others cannot: the **schema** fixes shape, the
**prompt** states intent, the **validator** enforces relationships.

### The 10 structural codes — the graph is malformed and must not be emitted

These are `validate`'s own. The seven that need a session are in the section before this one.

| Code | Fires when | In a schema? |
| --- | --- | --- |
| `duplicate_node_id` | Two or more nodes share an id | No — cross-object |
| `dangling_edge_ref` | An edge's `from_id` or `to_id` names no node | No — cross-object |
| `start_node_count` | Zero start nodes, or more than one | No — cross-object |
| `gateway_branches` | A gateway has fewer than two branches, **or** any branch has a null or blank condition | No — cross-object |
| `orphan_node` | A non-start with no incoming flow, or a non-terminal with no outgoing | No — cross-object |
| `terminal_unreachable` | No terminal exists, or some node reaches none. Walked **backwards from the terminals**, so a rework loop is not mistaken for a dead end | No — global |
| `unreachable_from_start` | A node not reachable forward from the start. Catches a self-consistent island that passes every local rule but is not part of the process | No — global |
| `malformed_annotation` | Four cases: an `annotates` edge leaving a non-annotation; one pointing *at* an annotation; an annotation wired into the flow by `precedes`/`branch`; an annotation describing nothing | No — cross-object |
| `missing_clarification_detail` | `needs_clarification` with an empty `detail`. An open question that does not say what is open tells a reviewer nothing, and it is a mechanical omission the model can fix from its own extraction | Yes, deliberately not |
| `missing_swimlane` | `actor` null or blank on any node. A box with no lane is one the renderer cannot place | Yes, deliberately not |

### The 3 resolution codes — well formed, but a human must resolve something

| Code | Fires when |
| --- | --- |
| `missing_required_subprocess` | The skeleton declares one no node claims — *"the source does not describe this; confirm it is genuinely absent"* |
| `unknown_subprocess` | A node claims a subprocess the skeleton does not declare |
| `needs_clarification` | One per tagged node, carrying its `detail` |

Severity is derived from the code by a lookup table inside `Finding.of`, so the two cannot
drift apart.

The ledger adds three more resolution codes of its own, described with it below.

**The split is the point of the stage.** Structural findings are mechanical — the model can
see the complaint and fix it, so they earn a repair turn. Resolution findings are ambiguity
in the source, which is *the product of this stage*, and are never retried. Retrying them
would only pressure the model into inventing content the source does not support, and an
invented step is indistinguishable from a real one everywhere downstream.

**One thing the validator cannot check.** It is never given `metadata.yaml` — the signature
is `validate(graph, skeleton)`. So it can require that a node names *a* lane, but has no list
to check the name against. A lane the config never declared reaches disk looking like any
other, and stage 2 draws it — after the declared lanes, with a warning in the log.

## 1H. The ledger, the candidates, and focus

All three are code. What counts as covered, what matters most next and where the discussion
is should not depend on a model's reading of a long conversation.

**The ledger** (`session/ledger.py`) has one entry per checklist topic.

| From | On | To |
| --- | --- | --- |
| `not_yet_covered` | asked | `asked`, `asked_count` + 1 |
| `asked` | answered | `present` · `confirmed_absent` · `needs_clarification` · `deferred` |
| `asked` | not answered | back to what it was, `asked_count` kept |
| any open status | mentioned unprompted | `present` · `needs_clarification` |
| `needs_clarification`, `deferred` | asked again | `asked` |
| any | its program fact denied, or its subprocess said not to exist | `not_applicable` |

A topic links to a node when they cite a common statement — set intersection, not judgement.
A scope is complete, by `process.yaml`, when every applicable topic of a required priority
has an accepted status and every `rule` terminal in it has been accepted at close-out.

Three resolution codes come from the ledger: `topic_without_nodes` (covered, but no step rests
on what was said), `open_topic` (a required-priority topic never settled, or any topic left
needing clarification) and `deferred_topic`.

**The candidates** (`session/candidates.py`), ranked:

| Rank | What |
| --- | --- |
| 1 | Structural gaps in the focus: a step whose outcome nobody stated, or one listing alternatives with no rule |
| 2 | The placeholder lane if any step sits in it; a lane whose role is unknown; an unexplained term |
| 3 | Screening topics whose program fact is still unknown |
| 4 | High-priority topics not yet covered, in the focus |
| 5 | Topics needing clarification, in the focus |
| 6 | Normal-priority gaps in the focus, then high-priority gaps in a subprocess the conversation has reached |
| 7 | Everything else |

Within a rank the order is the narrative's: checklist order for topics, graph order for
steps. Anything asked twice without an answer is marked `skip_offer`, sinks below everything
still askable, and is never asked a third time. The navigator is shown the top eight.

**Focus** (`session/focus.py`) starts on `main`. It moves into a subprocess when the user
asks, when an answer this turn was about it, or when the main flow has reached it and
nothing more pressing is open on the main flow. It returns when the subprocess has no open
high-priority topic and no open outcome. The navigator proposes; code accepts only what
these rules allow.

## 1I. The navigator

*What to ask next, where to focus, and what to say.* One conversation per turn. It cannot
edit the graph.

| | |
| --- | --- |
| Cached context | `navigator_knowledge(domain)`: every knowledge file and the whole checklist |
| Reads each turn | Phase and focus; a summary of the flow per scope, not JSON; this turn's findings; coverage; the ranked candidates; program facts; lanes and unexplained terms; the last few lines of transcript |
| Returns | `NavigatorResult`: `focus`, up to three `questions`, `reply`, `propose_close` |
| Failure | The reply falls back to an acknowledgement and the top candidate's own checklist question |

The navigator words a question; code decides what it is *about*. A question naming a
candidate takes that candidate's kind, steps, scope and subject, so a mis-copied id cannot
attach an answer to the wrong topic. A question of its own is kept as `suggested`, with only
the topic and step ids that exist. `propose_close` is honoured only when nothing at rank 6 or
above can still be asked.

Its style rules are in `agents/prompts/navigator.md`: open questions, never leading; the
user's own words; never another client's name or setup; never advice, never a comment on
compliance.

## 1J. What each failure does

| Failure | Behaviour |
| --- | --- |
| Interpreter cannot answer | Turn rejected, no state change, the user is asked to resend |
| Extractor exhausts its budget | The previous graph is kept; the statements are owed to the next turn; the page says the flow was not updated |
| Navigator cannot answer | The fallback reply, from the top candidate |
| The API refuses a request | Turn rejected, no state change, the user can retry — whichever agent hit it |
| The process restarts mid-turn | The turn's work was on a copy and is gone; `GET /sessions/{id}` reports it as failed so the page stops polling |

The duration of every step — the interpreter, each extraction attempt, the navigator — is
written to that turn's version record.

## 1K. Slicing and the live views

`session/slicing.py::slice_subprocess` cuts a subprocess out of the master graph: the tagged
nodes and the edges among them; one synthesised start labelled with `process.yaml`'s `entry`,
wired to every node entered from outside; and for every edge leaving, a synthesised terminal
— "Return to main flow: \<the step it returns to\>", or the outside terminal's own label
where the path ends the process there. Synthesised nodes are `origin: slice`. Subprocess tags
are cleared, and the result is checked with `validate`: a slice that fails is a defect in the
slicer.

`session/views.py` builds what the page draws, on every request, from the session alone:

| View | Content |
| --- | --- |
| Main | The master graph, each subprocess with steps collapsed to `sub:<id>`. Edges *leaving* a box are kept, unlike stage 2's fold, so the summary reads as one line |
| One per subprocess with steps | Its slice |

Annotations are not drawn; each becomes a note on the step it describes. Every node has a
`Rationale`: label, status, detail, the open question, the evidence as quote plus the
statement it came from and its turn, alternatives, notes, and the titles of linked topics.

## 1L. Close-out

`session/closeout.py`. On accept, for the main flow and each subprocess with steps:

| File | Content |
| --- | --- |
| `metadata.yaml` | `process_name` (`<process>` or `<process>_<subprocess>`); `actors` = the lanes that flow uses, ordered by `process.yaml`'s `typical_personas` then first appearance, each described by its persona's `lane_description` plus what the user said; `default_actor`; `glossary` = the domain's plus learned terms |
| `skeleton.json` | Main flow: the subprocesses that have steps, each in the lane of whoever hands off to it. Subprocess flows: `{"subprocesses": []}` |
| `outputs/graph.json` | The master graph, or the slice |
| `outputs/validation.json` | `validate`'s findings plus the ledger's for that scope |

### The flow folder in detail

Nobody writes these two files by hand; close-out composes them. They are documented because
they are stage 2's whole input besides the graph, and because the example folders under
`processes/` are hand-made instances of them.

**`metadata.yaml`**

| Field | Purpose |
| --- | --- |
| `process_name` | Machine name. **Every BPMN id in stage 2 is built from this** |
| `display_name` | Shown in prompts, page titles, and the diagram's pool |
| `actors` | Name → description. **Declaration order is lane order**, top to bottom. The lanes the flow uses |
| `default_actor` | Where a step lands when nobody is named. Must be one of `actors`, enforced by a model validator |
| `glossary` | Shorthand → meaning. Flagged to the model as "not actors" |

`actors` is not a fence: a node in a lane the file never lists is drawn after the listed
ones (see stage 2, job 1).

**`skeleton.json`**

The subprocesses that exist are declared once, in `process.yaml`, because they are **agnostic
across descriptions**: two people describing the same enrollment process will both hand off
to off-label review, whatever words they use. A flow's skeleton is the subset of them that
actually has steps.

| Field | Purpose |
| --- | --- |
| `name` | Matched against `Node.subprocess` |
| `label` | What the collapsed box is called |
| `actor` | The lane the box is drawn in. **Declared, not derived** — the lane that owns a subprocess is frequently not the lane performing most of its steps, and the box has no node of its own to take a lane from |

**There is no ordering field.** Declaration order in the file is presentation order: it sets
the sequence subprocesses are reported in by the validator.
It is not enforced — real descriptions run subprocesses in any order — and it places nothing,
because stage 2 draws each box where the first of its steps appeared.

**This list is what collapses, not a table of contents.** The running narrative belongs to no
subprocess and is drawn step by step. Listing a main-flow phase here would make it vanish
into a box.

**The test of that rule is the second example.** `processes/coverage_determination` describes four
named phases — PAP, shipment, prior authorization and appeals — and declares only the first
two. The rule that decides it is not "is this a phase?" but **does the source continue past
it?** Collapsing a box drops the edges leaving it and prunes whatever they alone led to. PAP
and shipment qualify because the document stops at them. Prior authorization and appeals do
not: both send a status back and the text runs on for another twelve lines, so collapsing
either would delete the appeal arc, the retry loop, the affordability checks — and PAP and
shipment along with them, since the only routes there run through prior authorization. It
would still validate, because a collapsed box is a legitimate end of a path. That is what
makes this the easiest field in the project to get quietly wrong.

The collapse pays for itself here. PAP is reached from four points in that document and
shipment from three; stage 2 re-points every entering edge at the box and de-duplicates, so
those seven arrows converge on two boxes instead of seven scattered end events.

### Drawing

Then, per flow, the calls `pipelines/stage2.py` and `pipelines/stage3.py` make: `translate`,
`render`, the layouter, `decisions.widen`, `colors.apply`, `page.build`. Everything is drawn
before anything is written, so a flow that cannot be drawn leaves no half-finished set of
folders. A folder close-out writes can be re-run with `pipelines.stage2 --processes-root`,
which is the check that no second copy of a stage crept in.

Stage 3 prints any finding code by its name and message, so the conversation's codes needed
no mapping there.

**One difference worth knowing.** Stage 2's fold ends each path at its subprocess box, so the
final main diagram does not show a subprocess flowing on to the next step, where the live
view does. Each subprocess's own diagram shows where it returns to.

## 1M. The HTTP surface and the page

Start-and-poll: a turn takes longer than a host will hold a request open. Every endpoint that
starts work answers `202`.

| Endpoint | Behaviour |
| --- | --- |
| `GET /health` | Liveness |
| `GET /processes` | The processes in `domain_knowledge/`, for the picker |
| `POST /sessions` | `{process_id, description}` → `{session_id}`, and queues turn 1. `422` empty, `413` over `PFG_MAX_SOURCE_CHARS`, `404` unknown process |
| `GET /sessions/{id}` | Phase, focus, turn, status and its sentence, transcript, pending questions, lanes, coverage, views with rationale, open items, outputs |
| `POST /sessions/{id}/messages` | `{text, quick_reply, question_id, item_key}`. `409` if a turn is running or the session is complete |
| `POST /sessions/{id}/focus` | `{focus}`: recorded, honoured on the next turn |
| `POST /sessions/{id}/close` | Enter close-out |
| `POST /sessions/{id}/accept` | Accept what is open and finalise |
| `GET /sessions/{id}/outputs` | The finished flows and their files |
| `GET /sessions/{id}/outputs/{flow}/{file}` | `diagram.bpmn`, `diagram.html` or `graph.json` |

Turns run on a small worker pool and are serialised per session: a second message to a busy
session is a `409`. A quick reply is sent as words as well as a flag, so the transcript reads
naturally and the interpreter treats a pressed button and a typed "not sure" alike.

The page is `frontend/`: Vite, React, TypeScript, `@xyflow/react` and `elkjs`, built to
`frontend/dist/` with a relative base and mounted at `/` when present, last, so the API keeps
its own paths. Three regions — chat, flow, side panel.
The flow is laid out by elk, layered, left to right, and re-laid out only when its shape
changes. It polls every 1.5 seconds while a turn is running and not otherwise. The status
line, the quick replies and every error sentence arrive from the service; the page prints
them.

## 1N. What gets logged

`utils/logs.py`. Configured by entry points only — `api/app.py` (the module uvicorn is
pointed at), `session/cli.py`, and the two `pipelines/*.py` `main`s — never by importing a
library module.

| Output | Answers | Content |
| --- | --- | --- |
| Console and `logs/app.log` | What happened, when, why | One line per decision, prefixed `[session tN role#attempt]`. At `DEBUG`, every prompt and response in full |
| `logs/trace.jsonl` | What exactly was sent and what came back | One object per model call: context, role, model, system prompt, prompt, response or error, seconds, token usage including cache read and write. The navigator's cached block is recorded by size, not copied |

Both files are opened in write mode by `configure_logging`, so each start overwrites them.

**Every model call is traced, by construction.** `extractors/model.py::_TracedAgent` wraps
the one Strands agent each conversation holds, and `StrandsConversation` calls a model only
through it. It times the call,
translates the SDK's exceptions, reads the token delta off the agent's running total, and
calls `record_call` whether the call succeeded or not.

**Context travels in a context variable.** `trace_context(session=, turn=, role=, attempt=)`
is set by the turn runner, the orchestrator and the extractor's loop, so a line written deep
in a validator says whose turn it belongs to without ids threaded through signatures. Turns
run on worker threads, and a context variable set in a worker is that worker's alone.

Our packages log at `PFG_LOG_LEVEL` (default `DEBUG`); everything else at `WARNING`.
uvicorn's own access log is separate and untouched.

---

# Stage 2 — graph to laid-out BPMN

```
processes/<name>/outputs/graph.json
            │
            ▼
     graph -> BPMN elements      (bpmn/semantics.py)
            │
            ▼
     semantic BPMN XML, no DI    (bpmn/document.py)
            │
            ▼
     bpmn-auto-layout            (bpmn/autolayout.py -> Node)
            │
            ▼
     outputs/diagram.bpmn        (BPMN 2.0 + full DI)
```

Deterministic: no model, no network, no credentials. The same graph always produces the same
bytes.

## 2A. First, what DI means

A BPMN 2.0 file has **two halves**.

| Half | Element | Says |
| --- | --- | --- |
| Semantic | `<bpmn:process>` with `task`, `exclusiveGateway`, `sequenceFlow`… | What the elements **are** and how they connect |
| Diagram interchange (**DI**) | `<bpmndi:BPMNDiagram>` → `<bpmndi:BPMNPlane>` → `<bpmndi:BPMNShape>` with `<dc:Bounds x y width height>`, and `<bpmndi:BPMNEdge>` with `<di:waypoint x y>` | Where each element is **drawn** |

A file with only the semantic half is **valid BPMN with no picture in it**. That is exactly
what this stage writes and hands to the layouter. Enrollment's finished file has the pool at
3532×1636 and the HCP lane at 3502×196.

Stage 2 computes **no geometry** except one deliberate exception, job 6 below.

## 2B. The seven jobs, in the order they happen

| # | Job | What it does | File |
| --- | --- | --- | --- |
| 1 | **Translate** | Every node becomes a BPMN element; every actor becomes a swimlane | `semantics.py` |
| 2 | **Fold** | Subprocesses collapse into single boxes, and the edges that leaves dangling are cleaned up | `semantics.py` |
| 3 | **Order** | Everything is sorted, because order is the only control this stage has over the picture | `semantics.py` |
| 4 | **Write** | The semantic XML, in a child order that is significant and unchecked | `document.py` |
| 5 | **Place** | A Node library computes every coordinate | `autolayout.py` |
| 6 | **Resize** | Gateways are redrawn to hold their question; events are widened to hold an oval | `decisions.py` |
| 7 | **Colour** | Events and collapsed subprocesses get fill and stroke written into the file | `colors.py` |

The graph is re-parsed against the schema on load but **not re-validated semantically** —
stage 1 already guarantees that.

## Job 1 — Translate

| IR node type | BPMN element |
| --- | --- |
| `start` | `startEvent` |
| `task` | `task` |
| `gateway` | `exclusiveGateway` |
| `terminal` | `endEvent` |
| `subprocess` | `subProcess` |
| `annotation` | `textAnnotation` |

Three places the mapping is **not** one-to-one, and each is a trap:

**Annotations are artifacts, not flow nodes.** A `textAnnotation` may never appear in a
lane's `flowNodeRef`, even though it is drawn inside the lane's band. Listing it there is the
commonest way to produce a file a modeller opens as empty.

**Associations point the other way.** The IR runs its `annotates` edge from the note to the
box it describes, because that is how the extractor thinks about it. BPMN runs the
association from the box to the note. The direction is flipped here, once.

**A branch's label is a `name`, never a `conditionExpression`.** It reads `Yes` or `No` from
`Edge.answer`, falling back to the source's own wording where the decision is not a yes/no
question. A `conditionExpression` is an executable predicate; these are sentences quoted from
a document.

Also here:

- A `needs_clarification` terminal becomes an ordinary `endEvent`. Marking it up is stage 3's
  job — inventing a notation here would put a claim in the file this stage cannot support.
- Ids are **derived, never generated**, and slugged to valid NCNames: no spaces, no
  punctuation beyond `_`, never a leading digit. "SP Biologics" fails all three. Prefixes are
  load-bearing, because stage 3's CSS has no other handle on element type: `Node_`, `Note_`,
  `Node_sub_`, `Lane_`, `Flow_`, `Association_`.
- **An undeclared lane is drawn, not refused.** `lane_order` returns the declared actors
  that are used, in declaration order, then any lane a node — or a collapsed box — names
  that `metadata.yaml` never declared, in order of first use, and logs a warning naming
  them. It used to raise. The declared list is a vocabulary the extractor is offered, and the
  extraction prompt itself says to "use the source's own wording" for someone outside it, so
  raising cancelled a whole run over a name the pipeline had asked for.
- Only lanes with something left in them get drawn, so declaring an actor the source never
  uses costs nothing but a line of config.

## Job 2 — Fold

The part worth reading slowly. Every subprocess named in `skeleton.json` becomes **one box**,
and the steps tagged with it are not drawn at all.

| Step | What happens |
| --- | --- |
| 1. Gather | For each declared subprocess, collect the nodes tagged with it — **except start events**, which are never swallowed |
| 2. Place the box | At the position of the **first** of its steps in the graph. Its lane comes from `skeleton.json` |
| 3. Edges in | Re-pointed at the box. Where several now connect the same pair, they are merged into one |
| 4. Edges out | **Dropped.** Nothing leaves a collapsed box |
| 5. Prune | Whatever those dropped edges alone led to goes with them |
| 6. Map | Every IR id — folded or stranded — is mapped to the box, so stage 3 can still point at something |

**Why nothing leaves the box.** A decision hands work off down a named path, and at this
level of the diagram that path is over when it reaches the box. So an edge running out of a
subprocess is dropped, and anything only that edge led to goes with it — an end state the
subprocess reached, the rest of a branch it rejoined. Whatever the main line still reaches,
such as a decision the subprocess happened to feed back into, survives untouched.

**The one thing that survives leaving a box** is a hand-off straight to another box. A source
that names one stretch of work and then names the next is still speaking at the level the
boxes are drawn at, and dropping the second would erase a section of the process rather than
fold it away.

**Why the start is hoisted back out.** A process with no visible entry point is not a
process. A start tagged into a subprocess is a tagging mistake, and drawing it is how that
gets noticed.

**Why merged edges lose their label.** Collapsing off-label review leaves three branches
running from the box to the same next decision, each giving a different reason for getting
there. The label survives only if every merged edge agreed on it — picking one of three to
print on the arrow would be a claim about the process that nothing supports.

Smaller rules:

- An edge whose ends both folded into the same box is an internal step, and is skipped.
- An annotation folded into a box is **dropped, not re-pointed** — a note describing a step
  the diagram no longer shows has nothing to say about it.
- A subprocess the skeleton does not declare is left **expanded**. The validator already
  reported it as `unknown_subprocess`, and folding it into a box named after a subprocess
  nobody declared would hide the same mistake twice.

**Consequence.** `skeleton.json` lists what *collapses*, not every phase of the process.
Tagging a main-flow step makes it disappear from the diagram. Nothing is lost on disk —
`graph.json` keeps every step, and questions raised inside a collapsed section stay in the
report, pointing at the box.

## Job 3 — Order

This stage computes no geometry, so **declaration order is the whole of its influence** over
the drawing: the layouter breaks ties on it.

| What | Ordered by |
| --- | --- |
| Flow nodes | The graph's own order, which follows the source narrative. Each collapsed box stands where the first of its steps stood |
| Edges | Source element position, then `Edge.order`, then graph index |

The second edge key is the one that matters: it makes a gateway's branches come out in the
order the extractor chose, which decides which way each is drawn — and later, which branch
gets first pick of a diamond corner. Shuffling either sort redraws the diagram without
changing its meaning.

## Job 4 — Write

Emits **no DI at all**: the layouter discards existing DI before generating its own, so
anything written here would be computed and then thrown away.

**Child order is significant and no schema checks it.** `tProcess` is a sequence:

```
laneSet  →  flow elements  →  artifacts
```

A `textAnnotation` emitted next to the tasks is out of order even though every element is
present. The usual symptom is a file that parses cleanly and opens blank.

A `collaboration` with a `participant` wraps the process rather than a bare process, because
the layouter selects one when present, and a pool is what gives the lanes something to sit
inside.

## Job 5 — Place

`bpmn-auto-layout`, run as a subprocess: XML on stdin, XML with full DI on stdout. Invoked
directly because its CLI already does exactly that, so a wrapper script would be a file to
maintain for nothing.

**Why this library.** It is a BPMN-specific layered layouter rather than a general graph one.
It knows that a lane constrains a node, that a gateway's branches are a narrative to be kept
near their spine, and that an edge must not cross a shape it has nothing to do with.

**Pinned to exactly `2.0.0-alpha.2`**, not a caret range. The stable 1.x line has no lane
support at all, and lanes are the point of this stage; 2.x is the rewrite that added them. An
alpha may change under a caret, and `tests/test_stage2_integration.py` is the regression
guard when it is bumped.

| Failure | Result |
| --- | --- |
| Binary missing or not executable | `LayoutError` naming the `npm ci` command |
| Non-zero exit | `LayoutError` carrying the layouter's stderr |
| Empty stdout | `LayoutError` |
| Warnings on stderr | Logged, never raised — JSON lines saying an element was not drawn. That is the layouter's judgement about a diagram it accepted, not a defect in what we sent |

**This is the only thing a *stage* runs under Node.** The other use of Node is the build
step that produces stage 3's page script (§3B) — which happens once, ahead of time, rather
than during a run.

## Job 6 — Fix the diamonds

The one place in the project that computes geometry, and a stated exception rather than a
hole in the rule.

**Problem one.** BPMN stores a gateway's name as an **external** label — a separate box with
its own coordinates — and bpmn-js hard-codes which element types have external labels, so no
styling moves it inside the shape. The layouter then finds each label a clear spot near its
diamond, which lands one question above its decision and the next below it. The shape is left
carrying nothing but an `X`, and the reader has to pair floating questions with shapes.

**Problem two.** The layouter runs every branch out of the **same** vertex and separates them
further along, leaving two arrows sharing a line and three corners of the diamond unused.

**What changes, per gateway:**

| Change | Detail |
| --- | --- |
| Diamond grows | 50×50 → **160×120**, about the same centre |
| Label moves inside | To the largest upright box that fits: 50% of each side, which is the biggest rectangle that fits in a diamond without crossing the slanted edges |
| Marker turned off | `isMarkerVisible="false"` **written** — in the file, not hidden in our stylesheet, so any other BPMN tool sees the same shape our page does. Written rather than removed, which is not the same thing: bpmn-js's modeler normalises the DI on import and reads a *missing* value as `true`, so deleting the attribute draws the very marker this line removes. Its viewer only ever read the attribute, which is why removal looked correct for as long as the page used one |
| Arrows re-aimed | Endpoints that met the old boundary are pushed out to the new one, along the axis they already lay on |
| Branches spread | A branch whose target is below leaves by the bottom point, one above by the top, each rebuilt as the two-segment L the layouter itself draws for that case, with its label brought along |

**What is deliberately left alone:**

- Branches running across the row keep the route they were given — that is what the layouter
  is best at, and those already leave from the right point.
- Only the **first** branch to want a corner gets it. A second descending branch keeps its
  route out of the right vertex, which is all the separation is for. "First" means first in
  `Edge.order`, because that is how job 3 emitted the flows.
- **Any rebuild that would cross a shape is abandoned** and the layouter's route stands. A
  cramped diagram is better drawn its way than with an arrow through a box. Lanes and the
  pool are excluded from the obstacle set, since they contain everything.
- A push that would take an endpoint past its neighbour is skipped.
- Every other shape, label and waypoint is written back exactly as it arrived.

The size is a **constant, not measured from the text**, so every decision reads as one kind
of thing. The layouter's 100px horizontal and 80px vertical gaps leave about 125px clear from
a gateway's centre, which is what makes 160×120 fit. If a question ever outgrows the box,
widen the constant rather than making the size depend on the wording.

Gateways are matched on any tag **ending** in `Gateway`, so a parallel gateway added later
gets the same treatment rather than silently keeping the old one. Events are matched the same
way on `Event`.

### Events are widened in the same pass

The page draws a start or an end as a **horizontal oval**, and the layouter sizes them 36×36
— square, with no room to be one. So they are grown about their centre to **80×40**, from the
same pass and for the same reason as the diamonds: the layouter sized a shape for the way
BPMN draws it by default, and this project draws it differently.

Events get the resize and the arrow push and nothing else:

- They are kept out of `_spread`, which reroutes *branches*. An event has one way in or one
  way out, and rerouting it would move a line the layouter had already placed well.
- Their label is left alone. It sits below the shape and was centred on the shape's centre,
  and growing about that centre leaves it centred still.
- The layouter spaces shapes 100px apart horizontally, so 22px added on each side still
  leaves a comfortable gap. The extra 4px of height is nothing against a vertical gap of 80.

## Job 7 — Colour

Written into the file, not into the page's stylesheet. BPMN carries colour as two
diagram-interchange attributes in a namespace the spec reserves for it, and
`getFillColor` consults them before anything else:

```
color:background-color  →  bioc:fill  →  a default
```

| Element | Fill | Stroke |
| --- | --- | --- |
| Start and end events | `#fde8e8` | `#b91c1c` |
| Collapsed subprocess | `#f3e8ff` | `#7e22ce` |

Pale fills with saturated strokes, so black label text stays readable on them.

**Why the file and not CSS.** A stylesheet colours our page and nothing else — a colleague
opening `diagram.bpmn` in Camunda would see plain black and white. bpmn-io's own
documentation lists CSS among the *non-recommended* ways to do this. An earlier version of
this project used CSS and was wrong to.

Only events and collapsed subprocesses are coloured. Colouring everything would say nothing;
the point is to make the entry, the exits, and the handed-off work findable at a glance.

This is deliberately **not** part of `decisions.py`. That module earns its exception to
"geometry is the layouter's" by being only geometry, and colour is a different concern that
happens to be written to the same elements.

**Exit codes:** `0` success · `1` layout failed, nothing written · `2` process unreadable,
not including a node in a lane the config never declared, which is drawn.

---

# Stage 3 — diagram to page

```
processes/<name>/outputs/diagram.bpmn ─┐
processes/<name>/outputs/validation.json ─┼─► page (render/page.py)
js/node_modules/bpmn-js               ─┘        │
                                                ▼
                                     outputs/diagram.html
```

## 3A. Inputs, and what is optional

| Input | Required? | If missing |
| --- | --- | --- |
| `outputs/diagram.bpmn` | **Yes** | Error naming the stage to run |
| `outputs/validation.json` | No | Warning; the page shows no open questions. A diagram is renderable whether or not the questions that came with it are still on disk |
| `outputs/graph.json` + `skeleton.json` | No | Warning; questions raised inside a collapsed subprocess are not clickable. Read for one purpose only: re-deriving stage 2's IR-id → BPMN-id map |
| `metadata.yaml` | Yes | The display name, for the title and header |
| `js/node_modules/bpmn-js/dist` | **Yes** | `AssetError` naming the install command |

The element map is **re-derived, not stored** — it is a pure function of the graph and the
skeleton, both already on disk, and a fourth output file would be one more thing to keep in
step with the three that matter.

**The script is our own bundle**, `js/dist/pfg-viewer.js`, built by esbuild from `js/src/`
and *not* one of bpmn-js's prebuilt files. The page needs a modeler **and** this project's
renderer, palette and read-only gate, and those are ES modules registered through
`additionalModules` — which is how bpmn-io's own examples extend bpmn-js, and it needs a
build. The prebuilt files are sealed: they reach nothing but the single global they expose.

The bundle is about 563 KB, which is most of why a page is nearer 730 KB than 350 KB.

**The stylesheets are not bundled.** They are read straight from `node_modules` and
concatenated in order — `diagram-js.css` (the canvas), `bpmn-js.css` (BPMN's own rules),
`bpmn-embedded.css` (the icon font). They need no compiling, and Python is what assembles
the page, so esbuild is left doing only the job it is good at.

That means `load_assets` reads from **two roots with two different remedies**: a missing
bundle means the *build* has not run, which `npm ci` alone will not fix, and that is the
likeliest mistake after a fresh clone.

### What is in the bundle

| Module | Does |
| --- | --- |
| `viewer.js` | The entry point, and the page's whole interface to bpmn-js: `window.PFG.createViewer(container)` and `window.PFG.setEditing(on)`. The page never constructs a modeler itself |
| `editGate.js` | The read-only state (§3D) |
| `renderer.js` | The two shapes drawn differently from stock BPMN (below) |
| `palette.js` | The palette cut down to what these diagrams are made of (below) |

### The two custom shapes

`PfgRenderer extends BaseRenderer` at **priority 1500**, above the default renderer's 1000,
which is the pattern bpmn-io's custom-rendering example uses.

| Element | Drawn as | Why |
| --- | --- | --- |
| Start and end events | A horizontal `<ellipse>` filling the bounds | Reads as a flowchart terminator rather than a small circle |
| Collapsed subprocess | bpmn-js's own box, plus a vertical bar inside each edge | The long-standing flowchart mark for "this box stands for work described elsewhere" — exactly what a collapsed subprocess is here |

Three details that matter:

- **`getShapePath` is implemented for events.** Without it a connection would be cropped
  against the bounding *box* rather than the oval, leaving a visible gap on the diagonals.
  It is bpmn-js's own `getCirclePath` with two radii instead of one.
- **The bars are inset by exactly 10px**, which is bpmn-js's `TASK_BORDER_RADIUS`. At any
  smaller inset a bar would meet the rounded corner rather than the straight top and bottom
  edges, and poke out of the shape at both ends.
- **`canRender` is deliberately narrow.** Everything else falls through to bpmn-js, which is
  better at drawing BPMN than we are. It also excludes elements with a `labelTarget` — an
  event's *label* is an element too, and would otherwise be drawn as a second oval.

Colour is not chosen here. It is read from the diagram with `getFillColor` and
`getStrokeColor`, so job 7 remains the one place colour is decided.

### The palette

Registered **below** the stock provider's priority so it runs after it, and returns an
*updater* — diagram-js hands it the entries collected so far, which is the supported way to
remove entries rather than only add them.

| | Entries |
| --- | --- |
| Kept | `start-event`, `end-event`, `task`, `exclusive-gateway`, `subprocess-expanded`, and every tool — hand, lasso, space, global-connect |
| Removed | `intermediate-event`, `data-object`, `data-store`, `group`, `participant-expanded` |
| Added | `text-annotation` |

The removals are all elements that would reach `bpmn/semantics.py` as something it has no
mapping for. The tools are kept because they are ways of working with what is on the canvas
rather than ways of putting new things on it.

**The text annotation is built, not kept.** bpmn-js never offered one from the palette — it
is a context-pad entry only — so this is a new entry rather than a survivor of the filter.

## 3B. Assembly

**One self-contained file.** The viewer, its stylesheets, the diagram and the questions are
all inlined; nothing is fetched when the page opens. Not a preference for big files: the page
is opened with Live Server or over `file://` from whatever folder the reader happens to point
at, and any relative `../../node_modules` path is broken by a different choice of root.
Inlining removes the question. It costs about 730 KB a page, most of it the modeler bundle,
which is why the page is generated rather than committed — and it is affordable because the
icon font is already a base64 data URI inside `bpmn-embedded.css`.

**`payload()` is what a page is told:**

| Key | Contents |
| --- | --- |
| `title` | The process's display name |
| `questions` | The panel, as **finished HTML** |
| `count` | How many, for the panel's toggle |
| `diagram` | The laid-out BPMN, DI included |
| `flagged` | The BPMN ids to mark, de-duplicated, in the order the panel names them |

**The panel is built in Python, not the browser.** The script never decides what the page
says — the panel is finished HTML in the markup. Escaping therefore has one home, and the
page's tests can assert what it says by reading it, with no browser involved.

| Mechanism | Detail |
| --- | --- |
| Sentinels | Five `<!--PFG:NAME-->` markers, filled by plain `str.replace`. Never `str.format` or `string.Template` — the file is full of CSS braces |
| Text escaping | `html.escape` for text and attributes |
| Payload escaping | `json.dumps`, **plus `<` escaped**. Inside a `<script>` the HTML parser is looking for one thing, a closing tag, so a diagram label reading `</script>` would end the block early and spill the document onto the page as text |
| Id translation | Findings carry IR ids; the page needs BPMN ids. `node_element_id` is **imported** from `bpmn.semantics`, never reimplemented — a slug rule in two places would eventually disagree, and the failure would be a highlight silently landing on nothing |
| Unclickable findings | A finding with no `node_ids` — a subprocess the source never described — gets no `data-elements` and is not clickable |
| What is inlined | `title` and `questions` are left out of the inlined payload, because they are already in the markup. Only what the viewer cannot read off the page travels as data, so the page reads correctly with no script run at all |

## 3C. What the finished page does

| Behaviour | Detail |
| --- | --- |
| Flagging | Every node a finding names gets an amber dashed outline |
| Two-way selection | Selecting a question scrolls the canvas to its box; selecting a marked box opens the panel and selects its question |
| The panel | A drawer floating **over** the canvas, not a column beside it, so showing or hiding it never resizes the diagram or moves a single box. A fit made while it is open fits to the part of the canvas still visible |
| Empty state | A graph with nothing outstanding says so |
| Fit | Centred in whatever slack the viewport leaves, and never magnified past life size |

**Appearance is decided in three places now**, and which one is right depends on what is
being changed:

| Change | Belongs in | Because |
| --- | --- | --- |
| Shape | `js/src/renderer.js` | BPMN cannot express "draw this as an oval" |
| Colour | `bpmn/colors.py` | It travels in the file, so every tool agrees |
| Everything else | this stylesheet | Neither of the above can express it |

What is left here is genuinely CSS-shaped:

| Selected by | Change | Why |
| --- | --- | --- |
| `Node_sub_` | The `+` marker is hidden | It promises an inside the diagram does not show |
| `Note_` | Drawn as a filled box | bpmn-js draws an annotation as an open bracket |
| `Association_` | Solid connector | bpmn-js draws it dotted |
| `…_label` | A background-coloured halo behind the glyphs | `Yes` and `No` sit on their arrow and are unreadable where the two cross. `_label` is the suffix diagram-js gives an external label, so this reaches text that floats free and never text set inside a box |

There is **no colour rule here**, deliberately. One would override the diagram's own colour
for our page alone, and the two would drift apart with nothing failing. The flagged-node
highlight *is* `!important`, so it still beats a colour arriving from the file — being unable
to see which boxes carry open questions is the one failure this page cannot afford.

The semantic file still says `subProcess` and `textAnnotation` regardless — any BPMN tool
opening it sees the real thing. This is the drawing only.

**Exit codes:** `0` success · `1` the page could not be built (bpmn-js not installed) ·
`2` the process or stage 2's diagram could not be read.

## 3D. Edit mode

The page carries an **Edit** toggle and a **Reset**. While editing is on the full bpmn-js
modeler is available — move, resize, rename, add, delete, re-route. **Nothing is saved.** A
reload restores the generated diagram, and no edit ever reaches disk or the API.

That is the whole feature, and the framing that makes it coherent is *scratchpad, not
editor*: rearrange the diagram to think about it, reload to get the generated truth back. It
is deliberately not a way to correct the extraction and keep the correction — that would need
a diagram → graph reverse mapping, which does not exist in any form.

Because nothing is ever written, **an edited diagram can never disagree with `graph.json`**,
and the export hazard never arises — no chance of the modeler writing back a gateway marker
`bpmn/decisions.py` turned off, because there is no export.

| Concern | How it is handled |
| --- | --- |
| A modeler is live from construction; bpmn-js offers no read-only switch | The page builds the off state itself. A module passed via `additionalModules` listens on `commandStack.<command>.canExecute` for every mutating command and returns `false` while editing is off |
| Those listeners must outrank bpmn-js's own rules | They register at priority 2000, above the 1000 `BpmnRules` uses, so they answer first and their refusal stands. Returning `undefined` while editing is on hands the decision back to bpmn-js |
| Why not one blanket veto | `canExecute` fires `commandStack.<command>.canExecute` and then the generic `commandStack.canExecute`, but a specific rule answering first cancels the bubble, so the generic is not reliably reached. A blanket veto would also catch the layout and resize work importing does for itself |
| Double-click rename opens without consulting a rule | `element.dblclick` is intercepted at the same priority, so the edit box never appears rather than appearing and silently declining to save |
| The palette and context pad are always in the DOM | Hidden by CSS while editing is off — the same id/class technique used to restyle annotations and collapsed boxes. Hidden rather than removed, because bpmn-js owns that DOM and puts it back |
| Reset | Re-imports the payload the page already holds and never mutates. It reuses `show()`, the same function that drew it the first time |

**Accepted, not solved:** the questions panel is never recomputed, so once anyone edits it
describes a diagram that no longer exists — a deleted box leaves a card pointing at nothing,
a renamed box no longer matches its question's wording, and an added box has no status
because nothing ever checked it. Nothing breaks (`mark()` and `select()` both test
`registry.get(id)` first, so dead cards go inert), and the notice on screen says so. Also
accepted: resizing a decision breaks the question-inside-the-diamond geometry, because
`bpmn/decisions.py` centres that label at exactly 50% inset and nothing re-centres it.
