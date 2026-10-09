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
    Both adapters build their client through `_client_args`, which adds the `anthropic-workspace-id` header when `ANTHROPIC_WORKSPACE_ID` is set -- a key not scoped to a workspace is refused without it.
  - `process.py` — the bounded retry loop. Depends on a `ModelCall` protocol, not the SDK, so it is exercised with no network.
  - `errors.py` — the retry taxonomy: a schema defect is repairable and earns a retry, an API rejection aborts immediately.
  - `conversation.py` — `ModelCall` made general, for the conversation's agents: `ConversationFactory.open(role, system_prompt, cached_context)` and `StructuredConversation.send(prompt, output)`. SDK-free like `process.py`; `model.py` implements it and is still the only file that imports Strands. `cached_context` goes in as the conversation's opening exchange ending in a cache point, **not** the system prompt -- Strands' Anthropic provider flattens the system prompt to a string and drops a cache point placed there.
- `validators/` — deterministic checks, no LLM. The "born valid" gate.
  - `predicates.py` — each check as a pure generator of findings, run over a `FlowView` (the graph minus annotations, which carry no sequence flow).
  - `graph.py` — composes them; the flow checks run only once ids are unique and every edge reference resolves, since otherwise they emit noise, not signal.
  - `report.py` — finding codes and the code→severity table. **Structural** findings block emission and drive a repair turn; **resolution** findings are tagged and shipped — they are the product of the stage, never a reason to retry.
  - `session_checks.py` — `validate_session(graph, corpus, lanes, process)`: the checks only a conversation can make, because only a session holds the statements and the lanes. Kept apart from `validate`, whose contract does not change. All structural. `evidence_not_found` is the one that makes extraction literal: every quote is looked up in the statement it cites.
- `domain_knowledge/` — the knowledge base the conversation runs on. **Data only, read-only at run time**; nothing a user says is ever written back into it.
- `knowledge/` — reads it. `schemas.py` is each file's shape, `extra="forbid"`. `loader.py` loads one process, markdown **agnostic first, then the process folder, sorted by path** -- load-bearing, since the navigator's cached block is built from it and must be byte-identical every turn. `compose.py` decides what each agent is told and is where the hardest rule lives: **domain knowledge drives questions, never content.** The navigator reads everything; the extractor reads lanes, glossary and subprocess ids and nothing else. `tests/test_knowledge_compose.py` asserts that, so it cannot erode by accident. Cross-file consistency of the data itself is `tests/test_domain_knowledge.py`.
- `agents/` — the conversation's three model calls, each one fresh conversation per turn, each answering in a Pydantic schema. `interpreter.py` reads a message against what was asked and never sees the graph. `extractor.py` turns new statements into a `GraphPatch` and is the only agent that writes the graph; its repair loop mirrors `extractors/process.py` but **returns** when the budget runs out instead of raising, because a session always has last turn's graph to keep. `navigator.py` chooses questions and writes the reply, and is the only agent that reads the knowledge base. `prompts/*.md` are the system prompts, filled by `str.replace` -- they are full of braces. **Every `description=` on these output models is prompt text**, as in `ir/models.py`.
- `session/` — the conversation around the agents. Deterministic, no LLM, and **code owns state**: no agent's memory of earlier turns is relied on for anything.
  - `models.py` — the session file. Records are frozen, `Session` is not: a turn works on a deep copy that replaces the original only on success, which is how "reject the turn, no state change" is kept.
  - `orchestrator.py` — `run_turn`, the seven steps, and what each failure does. Plain Python on purpose: no Swarm, no Graph, no interrupts, no Strands session manager. The human pause sits *between* turns, so there is no paused agent to resume.
  - `statements.py` — splits the first description by code, because statement text is what quotes are checked against. `patch.py` — `GraphPatch` and `apply_patch`, which never raises on a bad operation; it reports it, and that report is the repair prompt. In a partial update **null means unchanged**. `ledger.py` — topic status, moved only by code. `candidates.py` — what to ask next, ranked. `focus.py` — the navigator proposes a focus, code accepts it or not.
  - `slicing.py` — a subprocess flow cut from the master graph. **One master graph per session**; a subprocess is a tag, never a second copy, so the flows cannot disagree. `views.py` — the live-view payloads and per-step rationale, rebuilt on every request, never stored.
  - `closeout.py` — per-flow folders in the `processes/<name>/` layout, then the same calls stages 2 and 3 make. **No second copy of a stage**: a folder it writes can be re-run with `pipelines.stage2 --processes-root`.
  - `store.py` — `SessionStore` protocol and the file implementation, atomic by write-then-rename. `cli.py` — the terminal chat.
- `bpmn/` — stage 2 entire: a validated graph in, a rendered BPMN diagram out. Deterministic, no LLM.
  - `semantics.py` — what each element *is*, and the order it is declared in. Holds the mappings that are not one-to-one: an annotation is an artifact and may never appear in a lane's `flowNodeRef`; an association points from the annotated element to the note, the opposite of the IR edge. It is also where **subprocesses collapse**: every subprocess the skeleton declares becomes one childless `subProcess`, its steps are not drawn, and edges entering it are re-pointed at the box and de-duplicated. **Nothing leaves the box** — a path is over when it reaches one — so edges out of it are dropped and whatever they alone led to is pruned, while anything the main line still reaches survives. Only the start is hoisted back out. The box has no node to take a lane from, which is why `SubprocessSpec.actor` exists. `element_ids()` exports the resulting IR id → BPMN id map, folded *and* stranded nodes alike, because a finding raised on either still has to point somewhere; it comes from `_draw()` rather than from the collapse, since the map is only correct once the pruning has run. **Emission order is the only layout lever this project has** — the layouter computes all geometry and breaks ties on BPMN declaration order — so the sorts here are load-bearing, not cosmetic; flow nodes follow the graph's own order, with each box standing where the first of its steps stood.
  - `document.py` — the semantic XML, and **no diagram interchange at all**: the layouter discards existing DI before generating its own, so any written here would be thrown away. (The only DI this project ever writes is `decisions.py`'s geometry and `colors.py`'s colour, and both run *after* the layouter, on its output.) Child order is significant and unchecked by any schema: lane sets, then flow elements, then artifacts.
  - `autolayout.py` — the sole boundary to `bpmn-io/bpmn-auto-layout`, invoked as a subprocess. Semantic BPMN on stdin, BPMN with full DI on stdout.
  - `colors.py` — colour, written into the file rather than into a stylesheet. BPMN carries it as `color:background-color` / `color:border-color`, which is the first thing bpmn-js's `getFillColor` consults, so the page, Camunda and bpmn.io all draw the same diagram — something page CSS could never achieve. Deliberately **not** in `decisions.py`: that module earns its exception by being only geometry. Only events and collapsed subprocesses are coloured; colouring everything would say nothing.
  - `decisions.py` — **the one place in the project that computes geometry**, and a stated exception to the rule above rather than a hole in it. It exists because a gateway's name is an *external* label in BPMN and bpmn-js hard-codes which types those are, so no styling moves a question inside its diamond; the layouter then parks the label wherever it fits, above one decision and below the next, leaving the shape carrying nothing but an `X`. So after the layout is computed each gateway is redrawn: the diamond grows about its own centre to `DIAMOND`, the label moves to the largest upright box that fits inside it, `isMarkerVisible="false"` is **written** — which removes the `X` **in the file**, so another BPMN tool sees the same shape our page does, and is written rather than removed because bpmn-js's modeler normalises the DI on import and reads a *missing* value as `true`, so deleting the attribute draws the very marker the line exists to remove — and the arrows that met the old boundary are pushed out to the new one, along the axis they already lay on, and left alone where that would take them past their neighbour. The same pass **spreads the branches across the diamond's corners** (`_spread`): the layouter runs them all out of one vertex and separates them further along, so a branch whose target is below leaves by the bottom point and one whose target is above by the top, each rebuilt as the two-segment L the layouter itself draws for that case, with its label brought along. Branches running across the row keep the route they were given, only the first branch to want a corner gets it, and any rebuild that would cross a shape is abandoned — a cramped diagram is drawn the layouter's way rather than with an arrow through a box. It also **widens every start and end event** to `EVENT`, from the layouter's 36x36, because `js/src/renderer.js` draws those as horizontal ovals and a square has no room to be one. Events get the resize and the arrow push and nothing else -- they are kept out of `_spread`, which reroutes *branches*, something an event does not have. Nothing else is touched; every other shape, label and waypoint is written back as it arrived. Both `pipelines/stage2.py` and `api/pipeline.py` call it on whatever the layouter returned, so the two deliveries draw the same diagram.
- `render/` — stage 3 entire, and the hosted page: a laid-out diagram in, one self-contained HTML page out. Deterministic, no LLM.
  - `assets.py` — stage 3's **only** file reads, from two roots for two reasons: `js/dist/pfg-viewer.js`, **our own bundle** of bpmn-js plus `js/src/`, built by esbuild; and bpmn-js's stylesheets straight from `node_modules`, which need no compiling. Everything is inlined rather than linked, because Live Server's root is wherever the reader points it and any relative path into `node_modules` is broken by a different choice. The two carry different `AssetError` remedies on purpose: a missing bundle means the *build* has not run, which `npm ci` alone will not fix.
  - `template.html` — the shell, used **twice**. Appearance is decided in three places now, and which one is right depends on what is being changed: **shape** belongs in `js/src/renderer.js`, **colour** in `bpmn/colors.py` so it travels in the file, and only what neither can express belongs in this stylesheet. What is left here is genuinely CSS-shaped: a collapsed subprocess loses the `+` marker (it promises an inside the diagram does not show), an annotation is drawn as a filled box with a solid connector rather than bpmn-js's open bracket and dotted line, and an external label — a `Yes` or `No` sitting on its arrow — is given a background-coloured halo so it stays readable where the two cross. There is **no colour rule here**, deliberately: one would override the diagram's own colour for our page alone, and the two would drift with nothing failing. The flagged-node highlight is `!important` so it beats a colour arriving from the file. Selectors reach elements by the id prefix `bpmn/semantics.py` assigns, since a `textAnnotation` is a rect exactly as a task is. The semantic file keeps `subProcess` and `textAnnotation` regardless — any BPMN tool opening it sees the real thing; this is the drawing only, which is why `bpmn/semantics.py` gives annotations a `Note_` prefix. Used twice: stage 3's `diagram.html` arrives with a diagram inlined and opens on it; the hosted page arrives with none, opens on a form, and fetches the same payload from the API. One shell, so there is never a second copy of the viewer, the panel or the drawer to keep in sync. Filled by plain `str.replace` over `<!--PFG:NAME-->` comment sentinels, never `str.format` or `string.Template`: the file is full of CSS braces.
  - `page.py` — pure string assembly, no I/O, so a page is a function of its arguments. `payload()` is the single shape both deliveries use — the API returns it, `build()` inlines it — and it carries the questions panel as **finished HTML**, so Python decides what the panel says in both modes and the escaping has one home. Findings' `node_ids` are IR ids and the page needs BPMN ids, so it imports `bpmn.semantics.node_element_id` rather than repeating the slug rule.
- `api/` — the hosted demo's backend, and the only part of the project that answers HTTP. It **re-implements no stage**: `pipeline.py` composes the same functions the CLI orchestrators call, in memory, writing nothing — a hosted run belongs to whoever typed the text, not to the repo. `runs.py` starts runs on a single worker and remembers them in memory, because a run outlasts what a host will hold a connection open for, and polling is also what lets the page report a real stage. `app.py` takes the model and the layouter as constructor arguments, the same seam the CLI stages use, so the whole service is tested with no key, no network and no Node.
  `sessions.py` is the conversation's endpoints, mounted by `app.py` beside `/runs` and sharing nothing with it but the process. It keeps no session in memory -- only the ids with a turn in flight, which is what turns a second message to a busy session into a `409`. Everything the reader can read is worded there: the status line, the quick replies, the error sentence.
- `pipelines/` — orchestrators (`stage1.py`, `stage2.py`, `stage3.py`, `site.py`). Each composes one run: stage 1 reads `processes/<name>/inputs/…` → extractor returns a `ProcessGraph` → validator checks and tags → writes `processes/<name>/outputs/…`; stage 2 reads that graph → `bpmn/` → `outputs/diagram.bpmn`; stage 3 reads that diagram → `render/` → `outputs/diagram.html`. A graph failing the structural tier is never written, so later stages may assume anything in `outputs/` is well formed. `site.py` is not a stage: it builds the static page the demo is served from.
- `utils/` — `io.py` (read the input text, write output JSON) and `settings.py` (typed environment settings, loaded through a function rather than at import so the suite runs without an API key).
- `processes/<name>/` — data only, no code: `inputs/` (source documents), `outputs/` (generated `graph.json` and `validation.json`), `skeleton.json` (the subprocesses that collapse: drives the "is a part missing?" check and, in stage 2, which steps are folded into a box and which lane it lands in), `metadata.yaml` (display name, actors, glossary, optional model override). Adding a process = copy a folder and swap the data; the engine is untouched.
- `tests/` — schema round-trip, validator predicates, the retry loop against a fake model, IO, prompt assembly, the BPMN mapping and document, the page builder, the HTTP service, and every orchestrator end to end. For the conversation: `fakes.py` is one scripted `ConversationFactory`, which is enough to drive all three agents through the real pipeline; `test_session_loop.py` runs whole sessions turn by turn with it; `master_graph.py` is a graph touching all four subprocesses, shared by the slicing, view and close-out tests. No test touches the network. The layouter is a protocol and the viewer's files are an injected argument, so fakes cover most of the suite; the tests that need the real ones are marked `requires_node` (an install) or `requires_bundle` (an install *and* the build) and skip when either is absent. Two gates rather than one, because they are two different failures: stage 2 needs the layouter, stage 3 needs our own bundle, and gating both on one check would skip the layouter's tests on a machine that had merely not run the build. **The only tests that assert geometry are those and `test_bpmn_decisions.py`** — coordinates are otherwise not ours to produce, and a fake that invented plausible ones would only test itself. `test_bpmn_decisions.py` is the exception because `bpmn/decisions.py` is: it hands laid-out documents in by hand, since putting a shape exactly where a case needs it is the whole point. Likewise **no test drives a browser**: the page tests assert what the page *says*, and whether it *draws* is settled by opening it, which is a step to actually take rather than a gap to paper over.

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

Node is a committed build and CI dependency, alongside uv. **Three commands, not two** — the
build is not optional, and a missing bundle is the likeliest mistake after a fresh clone:

```bash
uv sync
npm ci --prefix js
npm run build --prefix js
```

`js/` holds `package.json`, the lockfile, and `src/` — **our own browser modules**. One
install serves two stages: `bpmn-auto-layout`, which stage 2 runs as a CLI, and `bpmn-js`,
which `src/` is bundled together with for stage 3. `node_modules/` and `dist/` are
gitignored; everything else there is committed.

`frontend/` is a **second, separate Node project**: the conversation's page, built by Vite to
`frontend/dist/` and served by the API at `/app`. It has its own `package.json` and lockfile
and shares nothing with `js/`. It exists because a chat, a live graph and a side panel that
all change on every poll are an application, not a page with a script; `js/` stays as trivial
as it was. Building it is needed only to use `/app`:

```bash
npm ci --prefix frontend
npm run build --prefix frontend
```

The rule below still holds for it: **the page never decides what it says.** The transcript,
the questions, the status sentence and the quick replies arrive from `api/sessions.py`.

**Nothing in this project runs under Node except the layouter and the two builds.** If a *stage*
needs something from that ecosystem at run time, front it with a Python module the way
`bpmn/autolayout.py` does rather than adding a script.

There was once a rule here that said "no bundler, no npm script and no `.js` file of ours on
disk". It is gone, and deliberately: extending bpmn-js means registering ES modules through
`additionalModules`, which is how bpmn-io's own examples do it, and that needs a build. What
the rule was protecting — one build toolchain, not two ecosystems tangled together — is kept
by keeping the build **trivial**: esbuild, one script, no config file, no Babel, no dev
server, sub-second. Python still assembles the page and still reads the CSS. If the build
ever needs a config file, that is a signal something has been put in the wrong language.

- `js/src/viewer.js` — the entry point, and the page's whole interface to bpmn-js:
  `window.PFG.createViewer(container)` and `window.PFG.setEditing(on)`. `template.html`
  never constructs a modeler itself.
- `js/src/editGate.js` — **Edit mode**, which is the page's alone: a modeler is live from
  construction and bpmn-js has no read-only switch, so the off state is built here. It vetoes
  every mutating command at priority 2000 — above the 1000 `BpmnRules` registers at — while
  CSS in `template.html` hides the palette and context pad. Editing is **session-only and
  never saved**, which is what keeps an edited diagram from ever disagreeing with
  `graph.json`, and is why no export exists to write back a gateway marker
  `bpmn/decisions.py` turned off. The questions panel is not recomputed after an edit; the
  page says so rather than pretending otherwise.
- `js/src/renderer.js` — the two shapes drawn differently from stock BPMN: events as
  horizontal ovals, a collapsed subprocess with a bar inside each vertical edge. `canRender`
  is narrow on purpose — everything else falls through to bpmn-js, which is better at drawing
  BPMN than we are. Colour is **not** chosen here: it is read from the diagram with
  `getFillColor`, so `bpmn/colors.py` is the one place it is decided.
- `js/src/palette.js` — the palette cut to what a diagram here is made of. Registered *below*
  the stock provider's priority so it runs after it and can return an updater that removes
  entries; a text annotation is *added* rather than kept, because bpmn-js never offered one
  from the palette.

The page script inside `render/template.html` still runs in the reader's browser and ships
as part of the page, and it drives the hosted demo — submit, retry, poll, swap views. What
holds, and is worth defending, is the narrower rule: **the script never decides what the page
says.** The panel arrives as finished HTML from `render/page.py` and is inserted; the
progress line is a sentence chosen in `api/runs.py` and printed. Anything the reader can read
is Python's to word and Python's to escape. If a change would have the browser build content
out of data, put it in `page.py` instead.

The layouter is pinned to an **exact pre-release** (`2.0.0-alpha.2`). That is deliberate:
the stable 1.x line has no lane support at all, and lanes are the point of stage 2. Do not
widen the pin to a caret — an alpha may change under it. `tests/test_stage2_integration.py`
is the regression guard when it is bumped.
