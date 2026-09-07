# Technical reference

What actually happens, stage by stage, at the level of files and functions. Read the
[README](README.md) first if you want the plain-language version — this document assumes you
want the detail.

Three stages. Only the first one calls a model; stages 2 and 3 are deterministic, and the
same input always produces byte-identical output.

---

# Stage 1 — source text to validated graph

```
processes/<name>/metadata.yaml  ─┐
processes/<name>/skeleton.json  ─┼─► system prompt ─► LLM ─► ProcessGraph
processes/<name>/inputs/*.md    ─┘                            │
                                                              ▼
                                                 validate(graph, skeleton)
                                                   │              │
                                        structural fail      structural pass
                                                   │              │
                                          repair prompt ──┘   outputs/graph.json
                                          (bounded retry)     outputs/validation.json
```

## 1A. What the system knows before it reads a word

Two of the three inputs are **process context** — things that are true of the process itself,
not of any particular description of it. They are stated once, by hand, and reused for every
run.

| Input | What it is | What it supplies |
| --- | --- | --- |
| `metadata.yaml` | Context about the process | The **actors**, which we model as **swimlanes** — each with a description, so the model can fill in the dots. A **default actor** for when it cannot tell who acts. A **glossary** of domain shorthand the writer may use without expanding |
| `skeleton.json` | The subprocesses of the main process | The named stretches of work that **collapse into a single box** in stage 2. Each has a machine name, a display label, and the lane its box is drawn in |
| `inputs/*.md` | The free-text description | The prose to extract from. `.md` or `.txt`, sorted by filename so a run is reproducible |

### `metadata.yaml` in detail

| Field | Purpose |
| --- | --- |
| `process_name` | Machine name. **Every BPMN id in stage 2 is built from this** |
| `display_name` | Shown in prompts, page titles, and the diagram's pool |
| `actors` | Name → description. **Declaration order is lane order**, top to bottom. Enrollment declares 9 |
| `default_actor` | Where a step lands when nobody is named. Must be one of `actors`, enforced by a model validator |
| `glossary` | Shorthand → meaning. Flagged to the model as "not actors" |
| `model_id` | Optional per-process model override |

**Why descriptions and not just names.** A model told only `JCRM` cannot know it is the
platform that runs the automations, so it cannot decide that an automated step belongs in
that lane. The description is what makes the assignment possible.

**Why a default actor.** Source documents describe automation in the passive voice
constantly — *"the PSM is assigned via zip to territory mapping"*. Without a default, a large
share of a real process arrives with no lane at all. Enrollment sends these to `PSCRM`.

### `skeleton.json` in detail

These are hardcoded because they are **agnostic across descriptions**: two people writing up
the same enrollment process will both hand off to off-label review, whatever words they use.
Stating them once is more reliable than rediscovering them per run.

| Field | Purpose |
| --- | --- |
| `name` | Matched against `Node.subprocess` |
| `label` | What the collapsed box is called |
| `actor` | The lane the box is drawn in. **Declared, not derived** — the lane that owns a subprocess is frequently not the lane performing most of its steps, and the box has no node of its own to take a lane from |

**There is no ordering field.** Declaration order in the file is presentation order: it sets
the sequence subprocesses are listed in for the prompt and reported in by the validator.
It is not enforced — real descriptions run subprocesses in any order — and it places nothing,
because stage 2 draws each box where the first of its steps appeared.

**This list is what collapses, not a table of contents.** The running narrative belongs to no
subprocess and is drawn step by step. Listing a main-flow phase here would make it vanish
into a box. Enrollment names four: off-label review, duplicate handling, and two missing-info
paths.

### `inputs/` is CLI-only

Worth stating plainly, because it is the easiest thing to misread. `metadata.yaml` and
`skeleton.json` are read from disk on **every** run, hosted or local. `inputs/` is **not**:
`api/pipeline.py` never imports `read_source`. Deployed, the text pasted into the form takes
its place, and nothing is read from `inputs/` at all.

## 1B. What the system prompt enforces

The schema carries per-field meaning. The prompt carries what a schema cannot express —
rules that span several fields or several objects. Together they aim at a graph that is
*born valid*, so the structural tier passes on the first attempt.

| Group | Rules |
| --- | --- |
| **Graph shape** | The graph is flat, never nested. Exactly one `start`, even where the source names several intake channels — those go in that node's label and detail. Every path reaches a terminal; loops are fine as long as some route out reaches one |
| **Decisions** | Every gateway gets at least two branches, each carrying a condition. Where the source gives only the happy path, emit the other branch, point it at a terminal, and mark that terminal `needs_clarification` — do not invent the outcome. Set `answer` to yes or no on each branch of a yes/no question, and still fill in `condition`. Keep a combined condition whole: *"18 or older AND the code is in the document"* is one condition, not two gateways |
| **Subprocess tagging** | A subprocess is work the source **hands off** at a decision, or a stretch the document gives its own heading. Tag every node on that path until it rejoins the main line. **The deciding gateway itself stays on the main line**, untagged, and so does the running narrative. Tagging stays flat — tagged steps are ordinary tasks and gateways with a tag, never a nested graph |
| **Honesty** | Two statuses and no middle ground. Competing outcomes with no stated rule go in `alternatives`, not into an invented gateway. Business rules and record values are annotations, never tasks, and never wired into the sequence flow |
| **Swimlanes** | Every box sits in one. A start, task or gateway takes the lane of whoever performs or decides. A **terminal takes the lane that owns the outcome**, which is often not the lane of the box pointing at it. An annotation takes the lane of the box it describes. Where nobody is named, the default lane |
| **Ids and order** | Unique snake_case ids. On edges leaving the same node, `order` starts at 0 and sets the sequence they are read in |

Assembled in four parts by `build_system_prompt`:

| Part | Contents |
| --- | --- |
| Role line | Names the process by `display_name` and states the job: capture what the source says, mark what it leaves open |
| Conventions | The fixed block above |
| Known subprocesses | The skeleton's names in declaration order, as the only values `subprocess` may take — explicitly *"not a checklist to satisfy"* |
| Swimlanes | The actors in declaration order with descriptions, plus the default-lane sentence. Omitted if none declared |
| Domain shorthand | The glossary, sorted. Omitted if empty |

## 1C. The call

| Step | Detail |
| --- | --- |
| Model | Strands `AnthropicModel`. `model_id` is the process override or the global default; `max_tokens` from settings. No temperature or top-p — current Claude models reject them |
| Schema delivery | The Pydantic model is handed over as a **tool**, via `structured_output_model=ProcessGraph`. Not requested in prose, so there is no parser to write for the ways a model can be slightly wrong |
| Conversation | The `Agent` is **held across calls**, so a repair turn continues the same conversation and the model sees its own previous graph beside the critique, rather than re-extracting from scratch |
| First turn | One line plus the source wrapped in `<source>` tags |

**The retry taxonomy** lives in the exception translation, and it is the whole of the
distinction:

| SDK failure | Becomes | Effect |
| --- | --- | --- |
| `StructuredOutputException` | `SchemaCallError` | Retry, quoting the complaint |
| `MaxTokensReachedException` | `SchemaCallError` | Retry — the graph was cut off mid-generation |
| `APIStatusError` | `ModelUnavailableError` | **Abort immediately.** No repair prompt fixes a bad key, a bad model id, or a quota |

`extractors/model.py` is the only file in the project that imports the SDK. The loop depends
on a `ModelCall` protocol instead, which is what lets it be tested with no network.

## 1D. Validation

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

**The split is the point of the stage.** Structural findings are mechanical — the model can
see the complaint and fix it, so they earn a repair turn. Resolution findings are ambiguity
in the source, which is *the product of this stage*, and are never retried. Retrying them
would only pressure the model into inventing content the source does not support, and an
invented step is indistinguishable from a real one everywhere downstream.

**One thing the validator cannot check.** It is never given `metadata.yaml` — the signature
is `validate(graph, skeleton)`. So it can require that a node names *a* lane, but has no list
to check the name against. An actor the model invented reaches disk looking perfectly valid,
and is caught in stage 2.

## 1E. The retry loop

Budget is `PFG_MAX_EXTRACTION_ATTEMPTS`, default 3, **including the first attempt**.

| Attempt outcome | Next prompt |
| --- | --- |
| `SchemaCallError` | Validation is skipped. Repair turn quotes the SDK's complaint and says to correct that and change nothing else |
| Structurally invalid | Repair turn lists `code: message` for each structural finding |
| Structurally valid | Return the graph, its report, and the attempt count |

The structural repair prompt says **"Fix only these defects — keep every other node and edge
as it was"**, and adds that where a defect exists because the source never states an outcome,
close it with a `needs_clarification` terminal rather than inventing what happens. Only
`report.structural` is ever fed back; resolution findings are never mentioned to the model.

Exhausting the budget raises `ExtractionError`, carrying the attempt count, the last report,
and the last schema complaint.

## 1F. Writing out

| Behaviour | Detail |
| --- | --- |
| Failure | A graph failing the structural tier is **never written**. Later stages may assume anything in `outputs/` is well formed |
| Name mismatch | If `graph.process_name` disagrees with the folder it is a **warning, not a failure** — a mislabelled but sound graph is worth keeping. Live example: enrollment's `graph.json` says `"Intake & Enrollment"`. Stage 2 therefore ignores that field entirely and builds ids from `metadata.yaml` |
| Files | `graph.json` and `validation.json`, two-space indented, `ensure_ascii=False`, trailing newline |
| Exit codes | `0` success · `1` extraction failed, nothing written · `2` process or configuration unreadable |

**What a real run produces.** The committed enrollment extraction has four findings, all
`needs_clarification`, all on terminals: the prescriber disagreeing, duplicate handling
resolved, an HCP still unresponsive, a manager not approving. Every one is a point where the
source stops before saying what happens next. That is the stage working as intended.

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

## 2B. The six jobs, in the order they happen

| # | Job | What it does | File |
| --- | --- | --- | --- |
| 1 | **Translate** | Every node becomes a BPMN element; every actor becomes a swimlane | `semantics.py` |
| 2 | **Fold** | Subprocesses collapse into single boxes, and the edges that leaves dangling are cleaned up | `semantics.py` |
| 3 | **Order** | Everything is sorted, because order is the only control this stage has over the picture | `semantics.py` |
| 4 | **Write** | The semantic XML, in a child order that is significant and unchecked | `document.py` |
| 5 | **Place** | A Node library computes every coordinate | `autolayout.py` |
| 6 | **Fix the diamonds** | Gateways are redrawn so each question sits inside its own shape | `decisions.py` |

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
- **The lane check stage 1 could not make.** `lane_order` raises if any node — or any
  collapsed box actually drawn — names an actor `metadata.yaml` does not declare. This is the
  first point the graph and the config are both in hand. A subprocess the skeleton declares
  but this description never mentions produces no box, so it names no lane and is not checked.
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

**This is the only thing in the project that runs under Node.** There is no bundler, no npm
script, and no JavaScript of ours on disk — except the page script in stage 3, which runs in
the reader's browser.

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
| Marker dropped | `isMarkerVisible` removed — **in the file**, not hidden in our stylesheet, so any other BPMN tool sees the same shape our page does |
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
gets the same treatment rather than silently keeping the old one.

**Exit codes:** `0` success · `1` layout failed, nothing written · `2` process unreadable,
including a node attributed to an undeclared actor.

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

**The viewer** is the *navigated* build: pan, keyboard move, zoom on scroll, no editing. The
page shows a result; an editable canvas would invite changes that go nowhere. Three
stylesheets are concatenated in order: `diagram-js.css` (the canvas), `bpmn-js.css` (BPMN's
own rules), `bpmn-embedded.css` (the icon font).

## 3B. Assembly

**One self-contained file.** The viewer, its stylesheets, the diagram and the questions are
all inlined; nothing is fetched when the page opens. Not a preference for big files: the page
is opened with Live Server or over `file://` from whatever folder the reader happens to point
at, and any relative `../../node_modules` path is broken by a different choice of root.
Inlining removes the question. It costs about 350 KB a page, most of it the viewer, which is
why the page is generated rather than committed — and it is affordable because the icon font
is already a base64 data URI inside `bpmn-embedded.css`.

**`payload()` is the one shape both deliveries use:**

| Key | Contents |
| --- | --- |
| `title` | The process's display name |
| `questions` | The panel, as **finished HTML** |
| `count` | How many, for the panel's toggle |
| `diagram` | The laid-out BPMN, DI included |
| `flagged` | The BPMN ids to mark, de-duplicated, in the order the panel names them |

**The panel is built in Python, not the browser.** The script never decides what the page
says — it inserts finished HTML. Escaping therefore has one home whichever way the payload
travels, and the page's tests can assert what it says by reading it, with no browser
involved.

| Mechanism | Detail |
| --- | --- |
| Sentinels | Seven `<!--PFG:NAME-->` markers, filled by plain `str.replace`. Never `str.format` or `string.Template` — the file is full of CSS braces |
| Text escaping | `html.escape` for text and attributes |
| Payload escaping | `json.dumps`, **plus `<` escaped**. Inside a `<script>` the HTML parser is looking for one thing, a closing tag, so a diagram label reading `</script>` would end the block early and spill the document onto the page as text |
| Id translation | Findings carry IR ids; the page needs BPMN ids. `node_element_id` is **imported** from `bpmn.semantics`, never reimplemented — a slug rule in two places would eventually disagree, and the failure would be a highlight silently landing on nothing |
| Unclickable findings | A finding with no `node_ids` — a subprocess the source never described — gets no `data-elements` and is not clickable |
| The offline page | Leaves `title` and `questions` out of the inlined payload, because they are already in the markup. Only what the viewer cannot read off the page travels as data, so the page reads correctly with no script run at all |

## 3C. What the finished page does

| Behaviour | Detail |
| --- | --- |
| Flagging | Every node a finding names gets an amber dashed outline |
| Two-way selection | Selecting a question scrolls the canvas to its box; selecting a marked box opens the panel and selects its question |
| The panel | A drawer floating **over** the canvas, not a column beside it, so showing or hiding it never resizes the diagram or moves a single box. A fit made while it is open fits to the part of the canvas still visible |
| Empty state | A graph with nothing outstanding says so |
| Fit | Centred in whatever slack the viewport leaves, and never magnified past life size |

**Restyling is by id prefix**, which is the only handle CSS has on element type:

| Prefix | Change | Why |
| --- | --- | --- |
| `Node_sub_` | The `+` marker is hidden | It promises an inside the diagram does not show |
| `Note_` | Drawn as a filled box | bpmn-js draws an annotation as an open bracket |
| `Association_` | Solid connector | bpmn-js draws it dotted |

The semantic file still says `subProcess` and `textAnnotation` regardless — any BPMN tool
opening it sees the real thing. This is the drawing only.

**Exit codes:** `0` success · `1` the page could not be built (bpmn-js not installed) ·
`2` the process or stage 2's diagram could not be read.

## 3D. The hosted delivery

```
GitHub Pages (static)                        Render (Docker: Python + Node)
┌────────────────────────┐  POST /runs       ┌──────────────────────────────┐
│ site/index.html        │ ────────────────► │ api/app.py    the endpoints  │
│  the same page shell,  │                   │ api/runs.py   runs in flight │
│  built with no diagram │  GET /runs/{id}   │ api/pipeline.py              │
│  in it yet             │ ◄──────────────── │   stages 1-3, nothing stored │
└────────────────────────┘   {status, …}     └──────────────────────────────┘
```

Stages 1 and 2 cannot run in a browser: one needs an API key, the other shells out to Node.
So the page is static and the pipeline is a service it calls.

**It re-implements no stage.** `api/pipeline.py` composes the same functions the CLI
orchestrators call, in memory. There is no second copy of a stage and there must never be
one — the demo exists to show what the pipeline does, so the moment it does something
slightly different it stops being a demo of anything.

| Endpoint | Behaviour |
| --- | --- |
| `GET /health` | Liveness, and the wake-up call the page makes on load |
| `GET /processes` | The processes that can be run, for the picker |
| `POST /runs` | Returns `202` and a run id. `422` if the description is empty, `413` if it exceeds `PFG_MAX_SOURCE_CHARS`, `404` if the process does not exist |
| `GET /runs/{id}` | Status, a human sentence, and the payload once it is done |

**Why start-and-poll.** A run takes a minute or two, longer than a host will hold a
connection open. Polling is also what lets the page report *which stage* is running instead
of spinning at nothing. Statuses run `queued` → `extracting` → `laying_out` → `rendering` →
`done` or `failed`, and each maps to a sentence chosen in Python and merely printed by the
browser.

| Decision | Detail |
| --- | --- |
| Runs in memory | Not durable, on purpose. A restart losing a run costs one press of Generate; a database to avoid that would be the largest thing in the repository. Fifty are kept, oldest forgotten first |
| A single worker | Two runs queue rather than competing for the same layouter subprocess and the same rate limit |
| Nothing written | No hosted run touches `processes/<name>/outputs/`. What someone types belongs to them, not to the repository |
| What is read | Only `metadata.yaml` and `skeleton.json` — the process context. **`inputs/` is not read**; the pasted text takes its place |
| Injected dependencies | The model and the layouter are constructor arguments, the same seam the CLI stages use, so the whole service is tested with no key, no network and no Node |
| Settings at run time | Loaded when a run begins, not at import, so a misconfigured instance answers `/health` and explains itself on the first run rather than crash-looping at boot |
| Same payload | The API returns exactly what stage 3 inlines, so from the moment it has data the hosted page and `diagram.html` are the same page |

**The endpoint is deliberately unguarded**: no rate limit, no passcode, and every run spends
a model call. That holds only while the URL is not shared. `PFG_MAX_SOURCE_CHARS` is about an
accidental paste, not an attacker.

The image carries Python and Node together, because a run is both stages. It also builds a
same-origin copy of the page and serves it at `/` — last, so it claims only the paths the API
did not — which costs nothing, needs no CORS, and is the answer if Pages is ever unavailable.
