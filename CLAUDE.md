# Proces Flow Generator

The future state vision of this project is to eventually be able to generate rendered bmpn process flows for patient support program business processes from just user input.

Which stage and which business process are in scope is given in the session prompt.
This file holds only what is true across all stages and processes.

# Repo structure

- `ir/` — the typed-graph schema and the per-process data models. The spine and single source of truth: the extractor targets it, the validator checks against it, later stages consume it.
  - `models.py` — Pydantic `Node` / `Edge` / `ProcessGraph`, all frozen and `extra="forbid"`. Deliberately **shape-only**: field types and non-emptiness, no graph semantics, so the validator's tests can construct broken graphs to prove the checks fire. Strands renders these models into the tool schema the model sees, so **every `description=` is prompt text** — edit it as carefully as the types. `Edge.answer` is the extractor's own word on which branch of a yes/no decision is which, and stage 2 draws it (`Yes` / `No`) in place of the condition; it is asked for rather than inferred from `Edge.order` or from the wording, because a diagram that is confidently backwards is worse than one that is wordy. Null where the decision is not a yes/no question, and then the condition is drawn.
  - `process_config.py` / `skeleton.py` — load `metadata.yaml` and `skeleton.json`, and own the folder-layout constants. `Node.subprocess` marks work the source **hands off** — the branch leaving "if it is off-label", or a stretch the document gives its own heading — and nothing else: the deciding gateway stays on the main line, and so does the running narrative. Stage 2 draws each tagged subprocess as one box, so `skeleton.json` lists the sections that collapse, not every phase of the process. Tagging a main-flow step makes it disappear from the diagram.
- `extractors/` — the LLM step: source text + process config → `ProcessGraph`. The only non-deterministic part.
  - `prompt.py` — all prompt text; pure string building, no I/O. Holds the cross-field conventions the schema cannot express.
  - `model.py` — the **sole** Strands/Anthropic boundary in the project. The agent is held across calls so a repair turn continues the same conversation.
  - `process.py` — the bounded retry loop. Depends on a `ModelCall` protocol, not the SDK, so it is exercised with no network.
  - `errors.py` — the retry taxonomy: a schema defect is repairable and earns a retry, an API rejection aborts immediately.
- `validators/` — deterministic checks, no LLM. The "born valid" gate.
  - `predicates.py` — each check as a pure generator of findings, run over a `FlowView` (the graph minus annotations, which carry no sequence flow).
  - `graph.py` — composes them; the flow checks run only once ids are unique and every edge reference resolves, since otherwise they emit noise, not signal.
  - `report.py` — finding codes and the code→severity table. **Structural** findings block emission and drive a repair turn; **resolution** findings are tagged and shipped — they are the product of the stage, never a reason to retry.
- `bpmn/` — stage 2 entire: a validated graph in, a rendered BPMN diagram out. Deterministic, no LLM.
  - `semantics.py` — what each element *is*, and the order it is declared in. Holds the mappings that are not one-to-one: an annotation is an artifact and may never appear in a lane's `flowNodeRef`; an association points from the annotated element to the note, the opposite of the IR edge. It is also where **subprocesses collapse**: every subprocess the skeleton declares becomes one childless `subProcess`, its steps are not drawn, and edges entering it are re-pointed at the box and de-duplicated. **Nothing leaves the box** — a path is over when it reaches one — so edges out of it are dropped and whatever they alone led to is pruned, while anything the main line still reaches survives. Only the start is hoisted back out. The box has no node to take a lane from, which is why `SubprocessSpec.actor` exists. `element_ids()` exports the resulting IR id → BPMN id map, folded *and* stranded nodes alike, because a finding raised on either still has to point somewhere; it comes from `_draw()` rather than from the collapse, since the map is only correct once the pruning has run. **Emission order is the only layout lever this project has** — the layouter computes all geometry and breaks ties on BPMN declaration order — so the sorts here are load-bearing, not cosmetic; flow nodes follow the graph's own order, with each box standing where the first of its steps stood.
  - `document.py` — the semantic XML, and **no diagram interchange at all**: the layouter discards existing DI before generating its own, so any written here would be thrown away. (The only DI this project ever writes is `decisions.py`'s, and that runs *after* the layouter, on its output.) Child order is significant and unchecked by any schema: lane sets, then flow elements, then artifacts.
  - `autolayout.py` — the sole boundary to `bpmn-io/bpmn-auto-layout`, invoked as a subprocess. Semantic BPMN on stdin, BPMN with full DI on stdout.
  - `decisions.py` — **the one place in the project that computes geometry**, and a stated exception to the rule above rather than a hole in it. It exists because a gateway's name is an *external* label in BPMN and bpmn-js hard-codes which types those are, so no styling moves a question inside its diamond; the layouter then parks the label wherever it fits, above one decision and below the next, leaving the shape carrying nothing but an `X`. So after the layout is computed each gateway is redrawn: the diamond grows about its own centre to `DIAMOND`, the label moves to the largest upright box that fits inside it, `isMarkerVisible` is dropped — which removes the `X` **in the file**, so another BPMN tool sees the same shape our page does — and the arrows that met the old boundary are pushed out to the new one, along the axis they already lay on, and left alone where that would take them past their neighbour. The same pass **spreads the branches across the diamond's corners** (`_spread`): the layouter runs them all out of one vertex and separates them further along, so a branch whose target is below leaves by the bottom point and one whose target is above by the top, each rebuilt as the two-segment L the layouter itself draws for that case, with its label brought along. Branches running across the row keep the route they were given, only the first branch to want a corner gets it, and any rebuild that would cross a shape is abandoned — a cramped diagram is drawn the layouter's way rather than with an arrow through a box. Only gateways are touched; every other shape, label and waypoint is written back as it arrived. Both `pipelines/stage2.py` and `api/pipeline.py` call it on whatever the layouter returned, so the two deliveries draw the same diagram.
- `render/` — stage 3 entire, and the hosted page: a laid-out diagram in, one self-contained HTML page out. Deterministic, no LLM.
  - `assets.py` — stage 3's **only** file reads: the vendored bpmn-js dist files, and the page shell. Everything is inlined rather than linked, because Live Server's root is wherever the reader points it and any relative path into `node_modules` is broken by a different choice.
  - `template.html` — the shell, used **twice**, and the one place the diagram's *appearance* is decided. bpmn-js's defaults are overridden there by id prefix, which is the only handle CSS has on element type: a collapsed subprocess loses the `+` marker (it promises an inside the diagram does not show), and an annotation is drawn as a filled box with a solid connector rather than bpmn-js's open bracket and dotted line. The semantic file keeps `subProcess` and `textAnnotation` regardless — any BPMN tool opening it sees the real thing; this is the drawing only, which is why `bpmn/semantics.py` gives annotations a `Note_` prefix. Used twice: stage 3's `diagram.html` arrives with a diagram inlined and opens on it; the hosted page arrives with none, opens on a form, and fetches the same payload from the API. One shell, so there is never a second copy of the viewer, the panel or the drawer to keep in sync. Filled by plain `str.replace` over `<!--PFG:NAME-->` comment sentinels, never `str.format` or `string.Template`: the file is full of CSS braces.
  - `page.py` — pure string assembly, no I/O, so a page is a function of its arguments. `payload()` is the single shape both deliveries use — the API returns it, `build()` inlines it — and it carries the questions panel as **finished HTML**, so Python decides what the panel says in both modes and the escaping has one home. Findings' `node_ids` are IR ids and the page needs BPMN ids, so it imports `bpmn.semantics.node_element_id` rather than repeating the slug rule.
- `api/` — the hosted demo's backend, and the only part of the project that answers HTTP. It **re-implements no stage**: `pipeline.py` composes the same functions the CLI orchestrators call, in memory, writing nothing — a hosted run belongs to whoever typed the text, not to the repo. `runs.py` starts runs on a single worker and remembers them in memory, because a run outlasts what a host will hold a connection open for, and polling is also what lets the page report a real stage. `app.py` takes the model and the layouter as constructor arguments, the same seam the CLI stages use, so the whole service is tested with no key, no network and no Node.
- `pipelines/` — orchestrators (`stage1.py`, `stage2.py`, `stage3.py`, `site.py`). Each composes one run: stage 1 reads `processes/<name>/inputs/…` → extractor returns a `ProcessGraph` → validator checks and tags → writes `processes/<name>/outputs/…`; stage 2 reads that graph → `bpmn/` → `outputs/diagram.bpmn`; stage 3 reads that diagram → `render/` → `outputs/diagram.html`. A graph failing the structural tier is never written, so later stages may assume anything in `outputs/` is well formed. `site.py` is not a stage: it builds the static page the demo is served from.
- `utils/` — `io.py` (read the input text, write output JSON) and `settings.py` (typed environment settings, loaded through a function rather than at import so the suite runs without an API key).
- `processes/<name>/` — data only, no code: `inputs/` (source documents), `outputs/` (generated `graph.json` and `validation.json`), `skeleton.json` (the subprocesses that collapse: drives the "is a part missing?" check and, in stage 2, which steps are folded into a box and which lane it lands in), `metadata.yaml` (display name, actors, glossary, optional model override). Adding a process = copy a folder and swap the data; the engine is untouched.
- `tests/` — schema round-trip, validator predicates, the retry loop against a fake model, IO, prompt assembly, the BPMN mapping and document, the page builder, the HTTP service, and every orchestrator end to end. No test touches the network. The layouter is a protocol and the viewer's files are an injected argument, so fakes cover most of the suite; the tests that need the real ones are marked `requires_node` and skip when Node is absent. **The only tests that assert geometry are those and `test_bpmn_decisions.py`** — coordinates are otherwise not ours to produce, and a fake that invented plausible ones would only test itself. `test_bpmn_decisions.py` is the exception because `bpmn/decisions.py` is: it hands laid-out documents in by hand, since putting a shape exactly where a case needs it is the whole point. Likewise **no test drives a browser**: the page tests assert what the page *says*, and whether it *draws* is settled by opening it, which is a step to actually take rather than a gap to paper over.

## Conventions (mandatory)

The Python skills in `.claude/skills/` are non-negotiable project conventions.
Consult and follow them when writing or reviewing Python: type-safety,
anti-patterns, code-style, testing, design-patterns, linting syntax, configuration, and docstrings.

ALWAYS update relevant document for READMEs, docstrings, comments, etc when making edits so these do NOT go stale!

## Strands

When writing or changing Strands code (agents, tools, structured output, model
providers), consult the Strands MCP (search_docs / fetch_doc) before relying on
memory. Verify APIs against the docs; don't guess.

## Node

Node is a committed build and CI dependency, alongside uv:

```bash
uv sync
npm ci --prefix js
```

`js/` at the repo root holds a `package.json` and a lockfile and **no source** — one install
serving two stages: `bpmn-auto-layout`, which stage 2 runs as a CLI, and `bpmn-js`, which
stage 3 inlines into its page. `node_modules/` is gitignored; `package.json` and
`package-lock.json` are committed.

**Nothing in this project runs under Node except the layouter.** There is no bundler, no npm
script and no `.js` file of ours on disk. If a stage needs something from that ecosystem,
front it with a Python module the way `bpmn/autolayout.py` does rather than adding a script.

The exception is the page script inside `render/template.html`, which runs in the reader's
browser and ships as part of the page. It used to decide nothing. It now also drives the
hosted demo — submit, retry, poll, swap views — so that is no longer true and should not be
claimed. What still holds, and is worth defending, is the narrower rule it was protecting:
**the script never decides what the page says.** The panel arrives as finished HTML from
`render/page.py` and is inserted; the progress line is a sentence chosen in `api/runs.py`
and printed. Anything the reader can read is Python's to word and Python's to escape. If a
change would have the browser build content out of data, put it in `page.py` instead.

The layouter is pinned to an **exact pre-release** (`2.0.0-alpha.2`). That is deliberate:
the stable 1.x line has no lane support at all, and lanes are the point of stage 2. Do not
widen the pin to a caret — an alpha may change under it. `tests/test_stage2_integration.py`
is the regression guard when it is bumped.
