# Proces Flow Generator

The future state vision of this project is to eventually be able to generate rendered bmpn process flows for patient support program business processes from just user input.

Which stage and which business process are in scope is given in the session prompt.
This file holds only what is true across all stages and processes.

# Repo structure

- `ir/` — the typed-graph schema and the per-process data models. The spine and single source of truth: the extractor targets it, the validator checks against it, later stages consume it.
  - `models.py` — Pydantic `Node` / `Edge` / `ProcessGraph`, all frozen and `extra="forbid"`. Deliberately **shape-only**: field types and non-emptiness, no graph semantics, so the validator's tests can construct broken graphs to prove the checks fire. Strands renders these models into the tool schema the model sees, so **every `description=` is prompt text** — edit it as carefully as the types. `Edge.answer` is the extractor's own word on which branch of a yes/no decision is which, and stage 2 draws it (`Yes` / `No`) in place of the condition; it is asked for rather than inferred from `Edge.order` or from the wording, because a diagram that is confidently backwards is worse than one that is wordy. Null where the decision is not a yes/no question, and then the condition is drawn.
  - `process_config.py` / `skeleton.py` — load `metadata.yaml` and `skeleton.json`, and own the folder-layout constants. `Node.subprocess` marks work the source **hands off** — the branch leaving "if it is off-label", or a stretch the document gives its own heading — and nothing else: the deciding gateway stays on the main line, and so does the running narrative. Stage 2 draws each tagged subprocess as one box, so `skeleton.json` lists the sections that collapse, not every phase of the process. Tagging a main-flow step makes it disappear from the diagram.
- `extractors/` — the model boundary. Nothing here knows what an agent is for; it is how any of them reaches a model.
  - `prompt.py` — `CONVENTIONS`, the cross-field rules a schema cannot express and that make a graph *born valid*. Quoted into the patch extractor's system prompt by `agents/extractor.py`. Prompt text: edit it as carefully as a type.
  - `model.py` — the **sole** Strands/Anthropic boundary in the project. A model is called from exactly one place in it, `_TracedAgent`, which times the call, translates the SDK's exceptions and records it; the agent is held for the life of one conversation, so a repair turn continues it, and never longer.
    The client is built by `_client_args`, which adds the `anthropic-workspace-id` header when `ANTHROPIC_WORKSPACE_ID` is set -- a key not scoped to a workspace is refused without it.
  - `errors.py` — the retry taxonomy: a schema defect is repairable and earns a retry, an API rejection aborts immediately.
  - `conversation.py` — the protocols the agents depend on instead of the SDK: `ConversationFactory.open(role, system_prompt, cached_context)` and `StructuredConversation.send(prompt, output)`. `model.py` implements them; tests implement them with a list of canned answers, which is why a whole session runs with no key. `cached_context` goes in as the conversation's opening exchange ending in a cache point, **not** the system prompt -- Strands' Anthropic provider flattens the system prompt to a string and drops a cache point placed there.
- `validators/` — deterministic checks, no LLM. The "born valid" gate.
  - `predicates.py` — each check as a pure generator of findings, run over a `FlowView` (the graph minus annotations, which carry no sequence flow).
  - `graph.py` — composes them; the flow checks run only once ids are unique and every edge reference resolves, since otherwise they emit noise, not signal.
  - `report.py` — finding codes and the code→severity table. **Structural** findings block emission and drive a repair turn; **resolution** findings are tagged and shipped — they are the product of the stage, never a reason to retry.
  - `session_checks.py` — `validate_session(graph, corpus, lanes, process)`: the checks only a conversation can make, because only a session holds the statements and the lanes. Kept apart from `validate`, whose contract does not change. All structural. `evidence_not_found` is the one that makes extraction literal: every quote is looked up in the statement it cites. **Lanes are deliberately not checked**: a lane the extractor names that the session has not learned is added as `proposed` by `session/orchestrator.py::learn_lanes` and becomes a question for the user.
- `domain_knowledge/` — the knowledge base the conversation runs on. **Data only, read-only at run time**; nothing a user says is ever written back into it.
- `knowledge/` — reads it. `schemas.py` is each file's shape, `extra="forbid"`. `loader.py` loads one process, markdown **agnostic first, then the process folder, sorted by path** -- load-bearing, since the navigator's cached block is built from it and must be byte-identical every turn. `compose.py` decides what each agent is told and is where the hardest rule lives: **domain knowledge drives questions, never content.** The navigator reads everything; the extractor reads lanes, glossary and subprocess ids and nothing else. `tests/test_knowledge_compose.py` asserts that, so it cannot erode by accident. Cross-file consistency of the data itself is `tests/test_domain_knowledge.py`.
- `agents/` — stage 1's three model calls, each one fresh conversation per turn, each answering in a Pydantic schema. `interpreter.py` reads a message against what was asked and never sees the graph. `extractor.py` turns new statements into a `GraphPatch` and is the only agent that writes the graph; its repair loop feeds back structural findings only and **returns** when the budget runs out rather than raising, because a session always has last turn's graph to keep. `navigator.py` chooses questions and writes the reply, and is the only agent that reads the knowledge base. `prompts/*.md` are the system prompts, filled by `str.replace` -- they are full of braces. **Every `description=` on these output models is prompt text**, as in `ir/models.py`.
- `session/` — **stage 1**: the conversation around the agents. Deterministic, no LLM, and **code owns state**: no agent's memory of earlier turns is relied on for anything.
  - `models.py` — the session file. Records are frozen, `Session` is not: a turn works on a deep copy that replaces the original only on success, which is how "reject the turn, no state change" is kept.
  - `orchestrator.py` — `run_turn`, the seven steps, and what each failure does. Plain Python on purpose: no Swarm, no Graph, no interrupts, no Strands session manager. The human pause sits *between* turns, so there is no paused agent to resume.
  - `statements.py` — splits the first description by code, because statement text is what quotes are checked against. `patch.py` — `GraphPatch` and `apply_patch`, which never raises on a bad operation; it reports it, and that report is the repair prompt. In a partial update **null means unchanged**. `ledger.py` — topic status, moved only by code. `candidates.py` — what to ask next, ranked. `focus.py` — the navigator proposes a focus, code accepts it or not.
  - `slicing.py` — a subprocess flow cut from the master graph. **One master graph per session**; a subprocess is a tag, never a second copy, so the flows cannot disagree. `views.py` — the live-view payloads and per-step rationale, rebuilt on every request, never stored.
  - `closeout.py` — per-flow folders in the `processes/<name>/` layout, then the same calls stages 2 and 3 make. **No second copy of a stage**: a folder it writes can be re-run with `pipelines.stage2 --processes-root`.
  - `store.py` — `SessionStore` protocol and the file implementation, atomic by write-then-rename. `cli.py` — the terminal chat.
- `bpmn/` — stage 2 entire: a validated graph in, a rendered BPMN diagram out. Deterministic, no LLM.
  - `semantics.py` — what each element *is*, and the order it is declared in. Holds the mappings that are not one-to-one: an annotation is an artifact and may never appear in a lane's `flowNodeRef`; an association points from the annotated element to the note, the opposite of the IR edge. It is also where **subprocesses collapse**: every subprocess the skeleton declares becomes one childless `subProcess`, its steps are not drawn, and edges entering it are re-pointed at the box and de-duplicated. **Nothing leaves the box** — a path is over when it reaches one — so edges out of it are dropped and whatever they alone led to is pruned, while anything the main line still reaches survives. Only the start is hoisted back out. The box has no node to take a lane from, which is why `SubprocessSpec.actor` exists. `lane_order` **draws a lane the config never declared** -- after the declared ones, in order of first use, with a warning -- where it once raised: the extraction prompt tells the model to use the source's own wording for someone outside the list, so refusing the diagram cancelled a run over a name the pipeline had asked for. `element_ids()` exports the resulting IR id → BPMN id map, folded *and* stranded nodes alike, because a finding raised on either still has to point somewhere; it comes from `_draw()` rather than from the collapse, since the map is only correct once the pruning has run. **Emission order is the only layout lever this project has** — the layouter computes all geometry and breaks ties on BPMN declaration order — so the sorts here are load-bearing, not cosmetic; flow nodes follow the graph's own order, with each box standing where the first of its steps stood.
  - `document.py` — the semantic XML, and **no diagram interchange at all**: the layouter discards existing DI before generating its own, so any written here would be thrown away. (The only DI this project ever writes is `decisions.py`'s geometry and `colors.py`'s colour, and both run *after* the layouter, on its output.) Child order is significant and unchecked by any schema: lane sets, then flow elements, then artifacts.
  - `autolayout.py` — the sole boundary to `bpmn-io/bpmn-auto-layout`, invoked as a subprocess. Semantic BPMN on stdin, BPMN with full DI on stdout.
  - `colors.py` — colour, written into the file rather than into a stylesheet. BPMN carries it as `color:background-color` / `color:border-color`, which is the first thing bpmn-js's `getFillColor` consults, so the page, Camunda and bpmn.io all draw the same diagram — something page CSS could never achieve. Deliberately **not** in `decisions.py`: that module earns its exception by being only geometry. Only events and collapsed subprocesses are coloured; colouring everything would say nothing.
  - `decisions.py` — **the one place in the project that computes geometry**, and a stated exception to the rule above rather than a hole in it. It exists because a gateway's name is an *external* label in BPMN and bpmn-js hard-codes which types those are, so no styling moves a question inside its diamond; the layouter then parks the label wherever it fits, above one decision and below the next, leaving the shape carrying nothing but an `X`. So after the layout is computed each gateway is redrawn: the diamond grows about its own centre to `DIAMOND`, the label moves to the largest upright box that fits inside it, `isMarkerVisible="false"` is **written** — which removes the `X` **in the file**, so another BPMN tool sees the same shape our page does, and is written rather than removed because bpmn-js's modeler normalises the DI on import and reads a *missing* value as `true`, so deleting the attribute draws the very marker the line exists to remove — and the arrows that met the old boundary are pushed out to the new one, along the axis they already lay on, and left alone where that would take them past their neighbour. The same pass **spreads the branches across the diamond's corners** (`_spread`): the layouter runs them all out of one vertex and separates them further along, so a branch whose target is below leaves by the bottom point and one whose target is above by the top, each rebuilt as the two-segment L the layouter itself draws for that case, with its label brought along. Branches running across the row keep the route they were given, only the first branch to want a corner gets it, and any rebuild that would cross a shape is abandoned — a cramped diagram is drawn the layouter's way rather than with an arrow through a box. It also **widens every start and end event** to `EVENT`, from the layouter's 36x36, because `js/src/renderer.js` draws those as horizontal ovals and a square has no room to be one. Events get the resize and the arrow push and nothing else -- they are kept out of `_spread`, which reroutes *branches*, something an event does not have. Nothing else is touched; every other shape, label and waypoint is written back as it arrived. Both `pipelines/stage2.py` and `session/closeout.py` call it on whatever the layouter returned, so a flow drawn at close-out and one drawn by the command are the same diagram.
- `render/` — stage 3 entire: a laid-out diagram in, one self-contained HTML page out. Deterministic, no LLM.
  - `assets.py` — stage 3's **only** file reads (it also inlines the two typefaces, Figtree and JetBrains Mono, from `js/node_modules/@fontsource-variable` as data URIs, so the page still fetches nothing), from two roots for two reasons: `js/dist/pfg-viewer.js`, **our own bundle** of bpmn-js plus `js/src/`, built by esbuild; and bpmn-js's stylesheets straight from `node_modules`, which need no compiling. Everything is inlined rather than linked, because Live Server's root is wherever the reader points it and any relative path into `node_modules` is broken by a different choice. The two carry different `AssetError` remedies on purpose: a missing bundle means the *build* has not run, which `npm ci` alone will not fix.
  - `template.html` — the shell of stage 3's `diagram.html`. Appearance is decided in three places now, and which one is right depends on what is being changed: **shape** belongs in `js/src/renderer.js`, **colour** in `bpmn/colors.py` so it travels in the file, and only what neither can express belongs in this stylesheet. What is left here is genuinely CSS-shaped: a collapsed subprocess loses the `+` marker (it promises an inside the diagram does not show), an annotation is drawn as a filled box with a solid connector rather than bpmn-js's open bracket and dotted line, and an external label — a `Yes` or `No` sitting on its arrow — is given a background-coloured halo so it stays readable where the two cross. There is **no colour rule here**, deliberately: one would override the diagram's own colour for our page alone, and the two would drift with nothing failing. The flagged-node highlight is `!important` so it beats a colour arriving from the file. Selectors reach elements by the id prefix `bpmn/semantics.py` assigns, since a `textAnnotation` is a rect exactly as a task is. The semantic file keeps `subProcess` and `textAnnotation` regardless — any BPMN tool opening it sees the real thing; this is the drawing only, which is why `bpmn/semantics.py` gives annotations a `Note_` prefix. The page arrives with its diagram inlined and fetches nothing. Filled by plain `str.replace` over `<!--PFG:NAME-->` comment sentinels, never `str.format` or `string.Template`: the file is full of CSS braces.
  - `page.py` — pure string assembly, no I/O, so a page is a function of its arguments. `payload()` is what a page is told, and `build()` inlines it; the questions panel is **finished HTML**, so Python decides what the panel says and the escaping has one home. Findings' `node_ids` are IR ids and the page needs BPMN ids, so it imports `bpmn.semantics.node_element_id` rather than repeating the slug rule.
- `api/` — the service, and the only part of the project that answers HTTP. It **re-implements nothing**: every turn is `session.orchestrator.run_turn` and every close-out is `session.closeout.finalise`, the calls the terminal chat makes. `app.py` builds the application -- `/health`, the session router, and the built page mounted at `/` last so the API keeps its own paths -- and takes the model, the layouter, the viewer's files and the store as arguments, so the whole service is tested with no key, no network and no Node.
  When `PFG_ACCESS_PASSWORD` is set, a middleware in `app.py` puts everything except `/health` behind HTTP Basic with that one shared password -- a door, not accounts. `/health` stays open because the host's health check cannot authenticate. Unset, the service is open and warns at startup.
  `sessions.py` is every endpoint that does anything, and the worker pool that runs turns. Start-and-poll, because a turn outlasts what a host will hold a connection open for, and polling is also what lets the page report a real step. It keeps no session in memory -- only the ids with a turn in flight, which is what turns a second message to a busy session into a `409`. Everything the reader can read is worded there: the status line, the quick replies, the error sentence.
- `pipelines/` — `stage2.py` and `stage3.py`: each stage as a command over one flow folder. Stage 2 reads `outputs/graph.json` → `bpmn/` → `outputs/diagram.bpmn`; stage 3 reads that diagram → `render/` → `outputs/diagram.html`. **Stage 1 has no orchestrator here: it is `session/`.** Close-out calls the same functions these do, in memory, and only writes a graph that passed the structural tier, so anything in `outputs/` is well formed.
- `utils/logs.py` — the console log, `logs/app.log` and `logs/trace.jsonl`, all **overwritten each start**. `configure_logging()` is called by entry points only, never on import of a library module (`api/app.py` is the exception, being what uvicorn imports). `trace_context(...)` carries session, turn, role and attempt in a context variable; `record_call(...)` writes one full trace line per model call and is invoked from `extractors/model.py::_TracedAgent`, the single place a model is called from -- **do not call a Strands agent anywhere else, or that call goes untraced.** Tests point `PFG_LOG_DIR` at a temp dir in `conftest.py` before anything imports.
- `utils/` — `io.py` (write a model to disk as JSON) and `settings.py` (typed environment settings, loaded through a function rather than at import so the suite runs without an API key).
- `processes/<name>/` — **example flow folders**, data only, in the layout close-out writes and stages 2 and 3 read: `metadata.yaml` (display name, the lanes in order with what each is, the default lane, glossary), `skeleton.json` (the subprocesses that collapse, and the lane each box lands in), `outputs/`. Nobody writes these by hand for a real flow any more; a session's are under `sessions/<id>/flows/<flow>/`. Kept for running stages 2 and 3 alone and for their tests.
- `tests/` — schema round-trip, both validators, the knowledge base's consistency, every deterministic step of a turn, the BPMN mapping and document, the page builder, the HTTP service, close-out, and stages 2 and 3 end to end. `fakes.py` is one scripted `ConversationFactory`, which is enough to drive all three agents through the real pipeline; `test_session_loop.py` runs whole sessions turn by turn with it; `master_graph.py` is a graph touching all four subprocesses, shared by the slicing, view and close-out tests. No test touches the network. The layouter is a protocol and the viewer's files are an injected argument, so fakes cover most of the suite; the tests that need the real ones are marked `requires_node` (an install) or `requires_bundle` (an install *and* the build) and skip when either is absent. Two gates rather than one, because they are two different failures: stage 2 needs the layouter, stage 3 needs our own bundle, and gating both on one check would skip the layouter's tests on a machine that had merely not run the build. **The only tests that assert geometry are those and `test_bpmn_decisions.py`** — coordinates are otherwise not ours to produce, and a fake that invented plausible ones would only test itself. `test_bpmn_decisions.py` is the exception because `bpmn/decisions.py` is: it hands laid-out documents in by hand, since putting a shape exactly where a case needs it is the whole point. Likewise **no test drives a browser**: the page tests assert what the page *says*, and whether it *draws* is settled by opening it, which is a step to actually take rather than a gap to paper over.

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

`frontend/` is a **second, separate Node project**: the page, built by Vite to
`frontend/dist/` with a relative base and served by the API at `/`. It has its own
`package.json` and lockfile and shares nothing with `js/`. It exists because a chat, a live
graph and a side panel that all change on every poll are an application, not a page with a
script; `js/` stays as trivial as it was. The service runs without it, and says so in the
log; building it is what puts a page at `/`:

```bash
npm ci --prefix frontend
npm run build --prefix frontend
```

**The look is the ZS theme**, and its tokens are named once at the top of
`frontend/src/styles.css`: Mango `#EC7700`, Mirage `#1A1628`, Moss `#A8D6B2`, the neutrals and
the three step statuses. `render/template.html` carries the same palette for stage 3's page,
and `bpmn/colors.py` the two colours written into the diagram itself. Two rules to keep:
**Mango is a fill, never text** (orange text is Deep orange `#A85400` on white and Light
orange `#F5A54D` on Mirage), and **selection is a Mirage ring behind a white gap**, never
colour alone. Fonts are Figtree and JetBrains Mono, bundled from `@fontsource-variable`, not
fetched.

It has two views: **requirements** (chat, live flow, side panel) and **diagrams**, which
shows each finished flow's `diagram.html` in an `<iframe>` served from
`/sessions/{id}/flows/{flow}/page`. The frame is stage 3's page whole and unmodified --
**do not rebuild the BPMN viewer in React**; Edit mode, the questions panel and zoom live in
that page and arrive with it.

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
as part of `diagram.html`: it imports the diagram, marks what is flagged, and wires the panel
to the canvas. What holds, and is worth defending, is the narrower rule: **the script never
decides what the page says.** The panel is finished HTML from `render/page.py`. Anything the
reader can read is Python's to word and Python's to escape. If a change would have the
browser build content out of data, put it in `page.py` instead.

The layouter is pinned to an **exact pre-release** (`2.0.0-alpha.2`). That is deliberate:
the stable 1.x line has no lane support at all, and lanes are the point of stage 2. Do not
widen the pin to a caret — an alpha may change under it. `tests/test_stage2_integration.py`
is the regression guard when it is bumped.
