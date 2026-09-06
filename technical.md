# Technical decisions

Why this project is built the way it is. The [README](README.md) says what it does and how
to run it; this file says what was chosen instead, and what each choice cost.

Every entry follows the same shape: **the decision**, **why**, and where it matters, **what
we gave up**.

---

## The shape of the whole thing

### One LLM step, three stages

**Decision.** The pipeline is split into three stages with a file between each: stage 1
reads the text and produces a graph, stage 2 draws the graph as BPMN, stage 3 wraps the
drawing in a web page. Only stage 1 talks to a model.

**Why.** Language models are the right tool for reading a messy document and the wrong tool
for placing boxes on a canvas. Keeping them apart means a drawing bug can never be a
prompting bug, and re-running stage 2 costs nothing while re-running stage 1 costs an API
call. It also means you can inspect the graph before anything is drawn from it.

**Cost.** Three commands instead of one, and files on disk between them.

### A typed graph in the middle

**Decision.** Everything meets at `ir/models.py` — a small Pydantic schema of `Node`,
`Edge`, `ProcessGraph`. The model fills it in, the validator checks it, stage 2 consumes it.

**Why.** Without a shared object in the middle, every stage would have its own idea of what
a "step" is and they would drift. One schema means one thing to change when the shape of the
data changes, and the type checker finds every place affected.

### The graph schema checks shapes, not meaning

**Decision.** The Pydantic models enforce field types and non-emptiness and nothing else.
"Ids must be unique", "edges must point at real nodes", "a gateway needs two branches" all
live in `validators/`, not in the model.

**Why.** Two reasons. First, the validator's tests have to be able to *build* a broken graph
in order to prove the validator catches it — impossible if the model rejects it first.
Second, keeping the rules in one place means later stages inherit a guarantee from the
validator rather than half-re-checking things themselves.

### Field descriptions are prompt text

**Decision.** The `description=` on every field in `ir/models.py` is treated as carefully as
the type next to it.

**Why.** Strands renders those models into the tool schema the model actually sees. Editing
a description changes extraction behaviour. This is easy to forget, which is why it is
written at the top of the file and again here.

### Data lives in folders, not in code

**Decision.** A process is `processes/<name>/` — a `metadata.yaml`, a `skeleton.json`, and
some input documents. Adding a process is copying a folder and swapping the contents. No
module anywhere knows the word "enrollment".

**Why.** The whole value of the project is that it generalises. If adding the second process
means writing code, it does not generalise.

---

## Stage 1 — reading the description

### Structured output through a tool schema, not "please return JSON"

**Decision.** The graph comes back through Strands' structured-output mechanism, which hands
the model the Pydantic schema as a tool.

**Why.** Asking for JSON in prose and parsing what comes back means writing a parser for
every way a model can be slightly wrong. The schema route makes the SDK responsible for that
and gives a clean exception when it fails.

### Two tiers of finding, and only one of them causes a retry

**Decision.** Validator findings are either **structural** (the graph is malformed — a
duplicate id, a gateway with one branch, a box with no swimlane) or **resolution** (the graph
is fine but a human must settle something). Structural findings block writing and trigger a
repair turn. Resolution findings are tagged, shipped, and never retried.

**Why.** This is the central idea of the project. A malformed graph is a mechanical mistake
the model can see and fix. Ambiguity in the source document is *not a mistake* — it is the
product of this stage. Retrying on it would just pressure the model into inventing content
the source never supported, which is the one failure mode that cannot be recovered from
downstream, because an invented step looks exactly like a real one.

**Cost.** A pipeline that sometimes hands back a diagram with open questions attached rather
than a confident-looking finished one. That is the intended trade.

### `stated` or `needs_clarification`, with no middle value

**Decision.** `NodeStatus` has exactly two values.

**Why.** A third value meaning "follows from how these processes usually work" sounds
reasonable and is a trap: nothing downstream can tell such a node from a stated one, so it
becomes an invented fact with a friendly label. If settling a question needs knowledge the
source does not contain, it is an open question.

### The retry loop keeps the same conversation

**Decision.** A repair turn continues the existing Strands agent rather than starting a new
call, so the model sees its own previous graph next to the critique.

**Why.** Re-extracting from scratch each time throws away work that was mostly right and
risks a different graph each attempt. Correcting one is a smaller, more reliable task.

### API failures abort; schema failures retry

**Decision.** `SchemaCallError` earns a retry. `ModelUnavailableError` — a bad key, a bad
model id, a quota — propagates immediately.

**Why.** No amount of re-prompting fixes an authentication failure. Retrying through one
burns the attempt budget and hides the actual problem behind a generic "extraction failed".

### The model is injected as a `Protocol`

**Decision.** `extractors/process.py` depends on a `ModelCall` protocol, not on Strands.
`extractors/model.py` is the only file in the project that imports the SDK.

**Why.** The retry loop is the most intricate logic in stage 1 and it is fully tested against
a fake that returns whatever a test wants — bad graphs, then a good one — with no network and
no API key. Same seam is reused by the CLI stages and the HTTP service.

### The prompt holds the cross-field rules

**Decision.** Per-field meaning lives in the schema descriptions. Rules that span fields —
one start node, every gateway gets two conditioned branches, business rules become
annotations rather than tasks, every box gets a swimlane — live in `extractors/prompt.py`.

**Why.** The schema physically cannot express "if this is a gateway then at least two edges
elsewhere in the graph must leave it". Putting those rules in the prompt is what makes the
graph *born valid* and lets the structural tier pass on the first attempt most of the time.

### Ambiguity gets a field instead of an invented gateway

**Decision.** When a source lists outcomes without saying which applies ("they either won't
be entered into the CRM or will just be archived"), both go into `Node.alternatives` on one
node.

**Why.** The alternative is a gateway whose conditions had to be made up. A made-up condition
is indistinguishable from a real one once it is drawn in a diamond.

### Every box sits in a swimlane, and a missing lane is structural

**Decision.** `actor` is required on every node — tasks, gateways, terminals, annotations
alike. A null lane fails the structural tier. Where the source names nobody, the box falls to
the process's declared `default_actor`.

**Why.** `actor` is the lane the box is *drawn in*, not merely who does the typing, so
"nobody performs an end state" is not a reason to leave it blank — a box with no lane is one
the renderer cannot place. And source documents describe automation in the passive voice
("the PSM is assigned via zip to territory mapping") constantly, so without a default lane a
large share of a real process would arrive unattributed.

**Limit.** The validator has no `ProcessConfig`, so it can only check that a lane was
*named*, not that it exists. Checking the name against the declared actors happens in stage
2, the first point the two can be compared.

### `Edge.answer` is asked for, not inferred

**Decision.** The extractor states which branch of a yes/no decision is the "yes". It is not
derived from `Edge.order`, and not derived from spotting the word "not" in the condition.

**Why.** A diagram that is confidently backwards is worse than one that is wordy. Inference
from wording works until it meets "unless the prescriber declines", at which point it is
silently wrong and looks correct. The full condition still lives in `graph.json` either way.

### A structurally invalid graph is never written

**Decision.** If no attempt clears the structural tier, stage 1 writes nothing and exits
non-zero.

**Why.** It lets every later stage assume that anything in `outputs/` is well formed, so
stage 2 has no re-validation code in it at all.

---

## Stage 2 — drawing the diagram

### We do not write a layout engine

**Decision.** Stage 2 emits BPMN with no coordinates in it and hands it to
`bpmn-io/bpmn-auto-layout`, which computes every shape bound, waypoint and label position.

**Why.** Graph layout is a genuinely hard problem and this library is BPMN-specific rather
than general: it knows a lane constrains where a node can go, that a gateway's branches are a
narrative that belongs near its spine, and that an edge must not cross a shape it has nothing
to do with. Writing that from scratch would be most of the project.

### The layouter is pinned to an exact pre-release

**Decision.** `bpmn-auto-layout` is pinned to `2.0.0-alpha.2` — an exact version, not a
caret range.

**Why.** This looks like an oversight and is not. The stable 1.x line has no lane support at
all, and lanes are the entire point of this stage. 2.x is the rewrite that added them. The
pin is exact because an alpha can change shape under a caret; `tests/test_stage2_integration.py`
is the regression guard for when it is bumped.

### Called as a subprocess, and the project contains no JavaScript

**Decision.** The layouter is invoked as a CLI with XML on stdin and XML on stdout, behind
one Python module. `js/` holds a `package.json`, a lockfile and no source.

**Why.** Its CLI already does exactly what is needed, so a wrapper script would be a file to
maintain for no gain. The rule this protects is bigger than the layouter: nothing in this
project runs under Node except third-party code, so there is no bundler, no npm script, and
nothing to keep in sync between two languages.

**Exception.** The page script inside `render/template.html` runs in the reader's browser —
see stage 3.

### Stage 2 writes no diagram interchange

**Decision.** `bpmn/document.py` emits the semantic tree only. Not one coordinate.

**Why.** The layouter discards existing DI before generating its own, so anything written
here would be computed and then thrown away.

### Emission order is the only layout lever, so the sorts are load-bearing

**Decision.** Flow nodes are declared in the graph's own order (which follows the source
narrative), each collapsed box standing where the first of its steps stood; a gateway's
branches go out in `Edge.order`.

**Why.** Since we compute no geometry, the only influence we have on the drawing is
declaration order — the layouter breaks ties on it. Reordering the emission redraws the
diagram without changing its meaning, which makes these sorts functional code rather than
tidiness.

### Child order in the XML is significant and nothing checks it

**Decision.** Lane sets, then flow elements, then artifacts — in that order, deliberately.

**Why.** `tProcess` is an XML sequence. A `textAnnotation` emitted next to the tasks is out
of order even though every element is present, and the usual symptom is a file that parses
cleanly and opens blank in a modeller. Same class of trap: a `textAnnotation` listed in a
lane's `flowNodeRef` — legal-looking, and the commonest way to make a file unopenable.

### The association direction is flipped, once

**Decision.** The IR runs its `annotates` edge from the note to the box. BPMN runs the
association from the box to the note. `bpmn/semantics.py` flips it.

**Why.** The IR direction is how the extractor thinks about it ("this note describes that
step"); the BPMN direction is what the spec requires. Rather than compromise either, the
conversion happens in exactly one place.

### A branch label is a `name`, never a `conditionExpression`

**Decision.** "Yes", "No", or the source's own wording, written as the flow's name.

**Why.** A `conditionExpression` is an executable predicate. These are sentences quoted out
of a Word document. Putting prose there would claim something about the file that is not
true.

### Subprocesses collapse, and nothing leaves the box

**Decision.** Every subprocess named in `skeleton.json` is drawn as one childless box; the
steps tagged with it are not drawn at all. Edges entering it are re-pointed at the box and
de-duplicated. Edges *leaving* it are dropped, along with anything only those edges led to.
Only the start event is ever hoisted back out.

**Why.** A decision hands work off down a named path, and at this level of the diagram that
path is over — the diagram should say so once rather than eleven times. Whatever the main
line still reaches (a decision the subprocess happened to feed back into, say) survives
untouched. The start is the one exception because a process with no visible entry point is
not a process; a start tagged into a subprocess is a tagging mistake, and drawing it is how
that gets noticed.

**Consequence.** `skeleton.json` lists the sections that *collapse*, not every phase of the
process. Tagging a main-flow step makes it vanish from the diagram. Nothing is lost on disk —
`graph.json` still holds every step.

### `SubprocessSpec.actor` is declared, not derived

**Decision.** The skeleton states which lane each collapsed box is drawn in.

**Why.** The box has no node of its own to take a lane from, and there is no rule to infer
one: the lane that *owns* a subprocess is frequently not the lane performing most of its
steps.

### `element_ids()` exports the IR-id → BPMN-id map

**Decision.** Stage 2 publishes what every IR node resolves to on the finished diagram —
including nodes folded into a box and nodes stranded behind one, which both map to that box.

**Why.** Stage 3 highlights the nodes a finding names. A question raised on a step inside a
collapsed subprocess still has to point at something the diagram contains, and the box is the
honest answer. The map comes from the drawing pass rather than the collapse because it is
only correct once the pruning has run.

### One place computes geometry, and it is a stated exception

**Decision.** `bpmn/decisions.py` runs *after* the layouter and redraws every gateway: the
diamond grows about its own centre to a fixed size, the question moves inside it,
`isMarkerVisible` is dropped, arrows that met the old boundary are pushed out to the new one,
and branches are spread across the diamond's corners.

**Why.** BPMN puts a gateway's name on an *external* label and bpmn-js hard-codes which types
have external labels, so no amount of CSS moves a question inside its diamond. The layouter
then parks each label wherever it fits — above one decision, below the next — leaving the
shape carrying nothing but an `X`, and a reader pairing floating questions with shapes.
Separately, the layouter runs every branch out of one vertex and separates them further
along, so two arrows share a line.

**How it is kept honest.** Only gateways are touched; every other shape, label and waypoint
is written back exactly as it arrived. Any rebuild that would cross a shape is abandoned — a
cramped diagram is drawn the layouter's way rather than with an arrow through a box. The
diamond is a constant rather than measured from the text, so decisions all read as one kind
of thing. Dropping the marker changes the *file*, so another BPMN tool sees the same shape
this project's page does.

### Ids are derived, never generated

**Decision.** Every BPMN id comes from the IR, slugged to a valid NCName. Nothing consults a
clock, a random source, or an unordered collection.

**Why.** The same graph produces byte-identical XML, which makes diffs meaningful and the
stage genuinely testable.

---

## Stage 3 — the page

### One self-contained HTML file

**Decision.** The bpmn-js viewer, its stylesheets, the diagram and the questions are all
inlined. The page fetches nothing when opened.

**Why.** The page is opened with Live Server, or straight off `file://`, from whatever folder
the reader happens to point at — and any relative `../../node_modules` path is broken by a
different choice of root. Inlining removes the question entirely.

**Cost.** About 350 KB a page, most of it the viewer. That is why the page is generated
rather than committed.

### One template, used twice

**Decision.** `render/template.html` is the shell for both the offline `diagram.html` and the
hosted page. The offline one arrives with a diagram inlined and opens on it; the hosted one
arrives with none, opens on a form, and fetches the same payload from the API.

**Why.** Otherwise there are two copies of the viewer, the panel and the drawer to keep in
sync, and they will diverge.

### Python decides everything the page says

**Decision.** The questions panel arrives as **finished HTML** built in `render/page.py`. The
progress line is a sentence chosen in `api/runs.py` and printed. The browser script submits,
polls, retries and swaps views — but never builds content out of data.

**Why.** It keeps every scrap of escaping on the Python side, with one home, whichever way
the payload travels. It also means the page's tests can assert what the page *says* by
reading it, with no browser involved.

### `payload()` is one shape, shared by both deliveries

**Decision.** The API returns it; `build()` inlines it. Same function, same keys.

**Why.** From the moment it has data, the hosted page and `diagram.html` are the same page. A
change to what a run produces reaches both, which is the point.

### Comment sentinels and `str.replace`, not a template engine

**Decision.** `<!--PFG:NAME-->` markers, filled by plain string replacement. Never
`str.format` or `string.Template`.

**Why.** The file is full of CSS braces. Both of those would choke on it, and adding a
template dependency to substitute five values would be the larger mistake.

### `<` is escaped in the embedded JSON

**Decision.** The payload goes through `json.dumps` and then `<` is escaped as well.

**Why.** Inside a `<script>` element the HTML parser is looking for one thing: a closing tag.
A diagram label reading `</script>` would end the block early and spill the rest of the
document onto the page as text. The panel's HTML travels through here too, so this is what
keeps it inert.

### Restyling is done by id prefix

**Decision.** Annotations get a `Note_` prefix so CSS can find them; the semantic file still
says `textAnnotation` and `subProcess`.

**Why.** Id prefix is the only handle CSS has on element type. The page draws a collapsed
subprocess without the `+` marker (it promises an inside the diagram does not show) and an
annotation as a filled box rather than bpmn-io's open bracket — but any BPMN tool opening the
`.bpmn` file still sees the real elements. The restyling is the *drawing*, not the data.

### The navigated viewer, not the modeller

**Decision.** `bpmn-navigated-viewer` — pan, keyboard move, zoom on scroll, no editing.

**Why.** The page shows a result. An editable canvas would invite changes that go nowhere,
and ships more code to do it.

### The questions panel floats over the canvas

**Decision.** A drawer over the diagram, not a column beside it.

**Why.** Showing or hiding a column resizes the canvas and moves every box on screen. A
floating drawer never does. A fit made while it is open fits to the part of the canvas still
visible.

---

## The hosted demo

### A static page plus a service, not one app

**Decision.** GitHub Pages serves the page; a Render container runs the pipeline.

**Why.** Stages 1 and 2 cannot run in a browser — one needs an API key, the other shells out
to Node. So the page is static and the pipeline is something it calls.

### The API re-implements no stage

**Decision.** `api/pipeline.py` composes the same functions the CLI orchestrators call, in
memory.

**Why.** The demo exists to show what the pipeline does. The moment it does something
slightly different, it stops being a demo of anything.

### Start-and-poll, not one long request

**Decision.** `POST /runs` returns an id; the page polls `GET /runs/{id}`.

**Why.** A run takes a minute or two, which is longer than a host in front of it will hold a
connection open. Polling is also what lets the page report *which stage* is running instead
of spinning at nothing.

### Runs live in memory, on one worker

**Decision.** A dict behind a lock, oldest finished runs forgotten, a single-worker thread
pool.

**Why.** This backs a demo. A restart losing a run costs one press of Generate; a database to
avoid that would be the largest thing in the repository. One worker means two runs queue
rather than competing for the same layouter subprocess and the same rate limit.

### A hosted run writes nothing to the repo

**Decision.** Nothing lands in `processes/<name>/outputs/`. Only the process *configuration*
is read from disk.

**Why.** What someone types belongs to them, not to the repository.

### The model and the layouter are constructor arguments

**Decision.** `create_app(call=..., layout=...)` — the same seam the CLI stages use.

**Why.** The entire HTTP service is tested with no API key, no network and no Node.

### Settings are loaded when a run begins, not at import

**Decision.** `load_settings()` is a function. There is no module-level singleton.

**Why.** A singleton makes importing anything in the package fail when `ANTHROPIC_API_KEY` is
unset — which is exactly the situation the test suite runs in. For the service it also means
a misconfigured instance answers `/health` and explains itself on the first run, rather than
crash-looping at boot where nobody can read the error.

### Stage 2 has its own settings class

**Decision.** `Stage2Settings` has every field defaulted and requires no API key.

**Why.** Stage 2 calls no model. Requiring credentials to draw a diagram from a graph already
on disk would be a startup failure for no reason.

### One Docker image with both runtimes

**Decision.** Python and Node in one image; Node copied from the official image rather than
installed from a distro package.

**Why.** A run is both stages. An image without Node would start, answer `/health`, and fail
every run at the point it tried to draw something. Node comes from the official image because
the layouter is pinned exactly and is the one thing that must not drift.

### The image also serves a copy of the page

**Decision.** `python -m pipelines.site --api-base ""` runs at build time, and the result is
mounted at `/` — last, so it claims only the paths the API did not.

**Why.** It costs nothing, needs no CORS because it is same-origin, and is the answer if
Pages is ever unavailable or misconfigured.

### The endpoint is deliberately unguarded

**Decision.** No rate limit, no passcode. Every run spends an Opus call.

**Why.** It is a demo, and the decision holds only while the URL is not widely shared. This
is recorded as a known exposure rather than an oversight. The one bound kept,
`PFG_MAX_SOURCE_CHARS`, is about an accidental paste — the difference between a run costing
cents and one costing a great deal more — and is not a security control.

---

## Engineering conventions

### Frozen models, `extra="forbid"`

**Decision.** Every Pydantic model in the project is immutable and rejects unknown fields.

**Why.** Immutability means no stage can quietly mutate what another stage is holding —
`validate()` returns findings and never touches the graph. `extra="forbid"` turns a typo in
a hand-edited `metadata.yaml` into an error instead of a silently ignored line.

### Strict typing, and a linter that is not just formatting

**Decision.** `mypy` in strict mode over the whole project; `ruff` with pyflakes, bugbear,
comprehensions, pyupgrade and simplify enabled.

**Why.** Most of this code shuttles structured data between stages, which is exactly the kind
of code a type checker catches mistakes in. Strict mode is what makes a schema change surface
every affected call site.

### A protocol at every boundary that is slow, paid, or external

**Decision.** `ModelCall` for the LLM, `Layouter` for the Node CLI, `ViewerAssets` for the
vendored bundle.

**Why.** Each is injected, so almost the whole suite runs with fakes: no network, no API key,
no Node, no 300 KB of vendor code inside a page test. The same seams are what let the HTTP
service be tested end to end.

### Geometry is asserted only where geometry is ours

**Decision.** The only tests that assert coordinates are the `requires_node` integration
tests and `test_bpmn_decisions.py`.

**Why.** Coordinates are the layouter's to produce. A fake that invented plausible ones would
only be testing itself. `test_bpmn_decisions.py` is the exception because `decisions.py` is —
it hands laid-out documents in by hand, since putting a shape exactly where a case needs it
is the whole point of those tests.

### No test drives a browser

**Decision.** The page tests assert what the page *says*. Whether it *draws* is settled by
opening it.

**Why.** A browser-driving suite for a static page would be the slowest and most brittle part
of the project, and it would still not prove the diagram looked right. Opening the page is a
step to actually take, not a gap to paper over.

### Tests that need Node skip rather than fail

**Decision.** The `requires_node` marker skips when Node or `js/node_modules` is absent.

**Why.** A contributor who has only run `uv sync` should get a green suite covering
everything that does not need the layouter, not a wall of errors about a missing binary.

### Not a distributable package

**Decision.** `[tool.uv] package = false`. The stages are top-level packages run from the
repo root.

**Why.** Nothing here is imported by anything else. Configuring a build backend for a thing
that is never built is ceremony.

### FastAPI is an optional dependency group

**Decision.** `uv sync` alone gives a working CLI pipeline with nothing web-shaped in it;
the service needs `--group api`.

**Why.** The CLI stages never import FastAPI, and someone running the pipeline locally should
not install a web framework to do it.

---

## Known trade-offs, stated plainly

- **The diagram can be wrong in ways nothing catches.** The validator proves a graph is well
  formed, not that it matches the document. A step attributed to the wrong lane is valid and
  wrong. The mitigation is that open questions are surfaced rather than hidden — not that the
  output is guaranteed correct.
- **Collapsed subprocesses hide real detail.** That is the intent at this zoom level, and
  `graph.json` keeps everything, but the drawn diagram is genuinely less than the extraction.
- **The layouter is an alpha.** Pinned exactly, guarded by an integration test, and still an
  alpha.
- **Run state does not survive a restart.** Acceptable for a demo, not for anything else.
- **The hosted endpoint costs money per press and is unguarded.** True while the URL is
  unshared; the first thing to change if it ever is.
