# Proces Flow Generator

The future state vision of this project is to eventually be able to generate rendered bmpn process flows for patient support program business processes from just user input.

Which stage and which business process are in scope is given in the session prompt.
This file holds only what is true across all stages and processes.

# Repo structure

- `ir/` — the typed-graph schema and the per-process data models. The spine and single source of truth: the extractor targets it, the validator checks against it, later stages consume it.
  - `models.py` — Pydantic `Node` / `Edge` / `ProcessGraph`, all frozen and `extra="forbid"`. Deliberately **shape-only**: field types and non-emptiness, no graph semantics, so the validator's tests can construct broken graphs to prove the checks fire. Strands renders these models into the tool schema the model sees, so **every `description=` is prompt text** — edit it as carefully as the types.
  - `process_config.py` / `skeleton.py` — load `metadata.yaml` and `skeleton.json`, and own the folder-layout constants.
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
  - `semantics.py` — what each element *is*, and the order it is declared in. Holds the mappings that are not one-to-one: an annotation is an artifact and may never appear in a lane's `flowNodeRef`; an association points from the annotated element to the note, the opposite of the IR edge. **Emission order is the only layout lever this project has** — the layouter computes all geometry and breaks ties on BPMN declaration order — so the sorts here are load-bearing, not cosmetic.
  - `document.py` — the semantic XML, and **no diagram interchange at all**: the layouter discards existing DI before generating its own, so any written here would be thrown away. Child order is significant and unchecked by any schema: lane sets, then flow elements, then artifacts.
  - `autolayout.py` — the sole boundary to `bpmn-io/bpmn-auto-layout`, invoked as a subprocess. Semantic BPMN on stdin, BPMN with full DI on stdout.
- `render/` — stage 3 entire, and the hosted page: a laid-out diagram in, one self-contained HTML page out. Deterministic, no LLM.
  - `assets.py` — stage 3's **only** file reads: the vendored bpmn-js dist files, and the page shell. Everything is inlined rather than linked, because Live Server's root is wherever the reader points it and any relative path into `node_modules` is broken by a different choice.
  - `template.html` — the shell, used **twice**: stage 3's `diagram.html` arrives with a diagram inlined and opens on it; the hosted page arrives with none, opens on a form, and fetches the same payload from the API. One shell, so there is never a second copy of the viewer, the panel or the drawer to keep in sync. Filled by plain `str.replace` over `<!--PFG:NAME-->` comment sentinels, never `str.format` or `string.Template`: the file is full of CSS braces.
  - `page.py` — pure string assembly, no I/O, so a page is a function of its arguments. `payload()` is the single shape both deliveries use — the API returns it, `build()` inlines it — and it carries the questions panel as **finished HTML**, so Python decides what the panel says in both modes and the escaping has one home. Findings' `node_ids` are IR ids and the page needs BPMN ids, so it imports `bpmn.semantics.node_element_id` rather than repeating the slug rule.
- `api/` — the hosted demo's backend, and the only part of the project that answers HTTP. It **re-implements no stage**: `pipeline.py` composes the same functions the CLI orchestrators call, in memory, writing nothing — a hosted run belongs to whoever typed the text, not to the repo. `runs.py` starts runs on a single worker and remembers them in memory, because a run outlasts what a host will hold a connection open for, and polling is also what lets the page report a real stage. `app.py` takes the model and the layouter as constructor arguments, the same seam the CLI stages use, so the whole service is tested with no key, no network and no Node.
- `pipelines/` — orchestrators (`stage1.py`, `stage2.py`, `stage3.py`, `site.py`). Each composes one run: stage 1 reads `processes/<name>/inputs/…` → extractor returns a `ProcessGraph` → validator checks and tags → writes `processes/<name>/outputs/…`; stage 2 reads that graph → `bpmn/` → `outputs/diagram.bpmn`; stage 3 reads that diagram → `render/` → `outputs/diagram.html`. A graph failing the structural tier is never written, so later stages may assume anything in `outputs/` is well formed. `site.py` is not a stage: it builds the static page the demo is served from.
- `utils/` — `io.py` (read the input text, write output JSON) and `settings.py` (typed environment settings, loaded through a function rather than at import so the suite runs without an API key).
- `processes/<name>/` — data only, no code: `inputs/` (source documents), `outputs/` (generated `graph.json` and `validation.json`), `skeleton.json` (expected subprocesses, drives the "is a part missing?" check), `metadata.yaml` (display name, actors, glossary, optional model override). Adding a process = copy a folder and swap the data; the engine is untouched.
- `tests/` — schema round-trip, validator predicates, the retry loop against a fake model, IO, prompt assembly, the BPMN mapping and document, the page builder, the HTTP service, and every orchestrator end to end. No test touches the network. The layouter is a protocol and the viewer's files are an injected argument, so fakes cover most of the suite; the tests that need the real ones are marked `requires_node` and skip when Node is absent. **Nothing outside those asserts geometry** — it is not ours to produce, and a fake that invented plausible coordinates would only test itself. Likewise **no test drives a browser**: the page tests assert what the page *says*, and whether it *draws* is settled by opening it, which is a step to actually take rather than a gap to paper over.

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
