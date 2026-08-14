# Process Flow Generator

Turns a written description of a patient support program business process into a typed,
validated process graph — on the way to rendered BPMN diagrams generated from user input
alone.

The hard part is not drawing boxes. It is that real process descriptions are incomplete:
they give the happy path, name three intake channels for one request, and stop before
saying what happens when someone disagrees. So the graph this produces is explicit about
what the source actually supports. Every node is either `stated` or `needs_clarification`,
and every open question is reported for a human rather than quietly invented.

Actors are swimlanes. Every box sits in one — a step in the lane that performs it, a
gateway in the lane that decides, a terminal in the lane that owns the outcome, an
annotation in the lane of the box it describes. A box with no lane is one the renderer
cannot place, so it fails the structural tier; where the source names nobody, the box
falls to the process's declared default lane rather than to a blank.

## Stage 1

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

The design turns on one distinction:

- A **mechanical** defect — the response did not fit the schema, or the graph breaks a
  structural rule such as a gateway with one branch — is something the model can see and
  fix. It earns a retry with the specific complaint fed back.
- **Ambiguity** in the source is not a defect. It is the output of this stage. Resolution
  findings never trigger a retry; retrying them would only pressure the model into
  inventing content the source does not support.

A graph that fails the structural tier is never written, so later stages may assume
anything in `outputs/` is well formed.

## Stage 2

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

Entirely deterministic: no model, no network, no credentials. The same graph always
produces byte-identical XML.

This stage computes **no geometry**. It emits semantic BPMN — a pool, one lane per actor,
flow elements, artifacts — and hands it to `bpmn-io/bpmn-auto-layout`, which generates
every shape bound, waypoint and label bound. That library is a BPMN-specific layered
layouter rather than a general graph one, which is the whole reason it is here: it knows
that a lane constrains a node, that a gateway's branches are a narrative to be kept near
their spine, and that an edge must not cross a shape it has nothing to do with.

The consequence is that the one lever this stage holds is **declaration order**, since the
layouter breaks ties on it. Flow nodes go out in the skeleton's subprocess order, which is
what puts intake before onboarding; a gateway's branches go out in `Edge.order`, which
decides which way each is drawn.

The layouter is pinned to an exact pre-release, `2.0.0-alpha.2`. The stable 1.x line has no
lane support at all, and lanes are the point of the stage.

## Stage 3

```
processes/<name>/outputs/diagram.bpmn ─┐
processes/<name>/outputs/validation.json ─┼─► page (render/page.py)
js/node_modules/bpmn-js               ─┘        │
                                                ▼
                                     outputs/diagram.html
```

One self-contained HTML file: the bpmn.io viewer, its stylesheets, the diagram and
the open questions are all inlined, so nothing is fetched when it is opened. Open it
with Live Server, or straight off the filesystem.

Self-contained because Live Server's root is wherever you point it, and any relative
path into `node_modules` is broken by a different choice of folder. The cost is about
350 KB a page, most of it the viewer, which is why the page is generated rather than
committed.

This is where `needs_clarification` finally shows: every node a finding names is drawn
with an amber dashed outline, and the questions are listed beside the diagram rather
than left in a JSON file next to it. Selecting a question finds its box; selecting a
marked box finds its question. A graph with nothing outstanding says so.

## Running it

```bash
uv sync
npm ci --prefix js               # the BPMN layouter and viewer
echo "ANTHROPIC_API_KEY=sk-..." > .env
uv run python -m pipelines.stage1 --process enrollment
uv run python -m pipelines.stage2 --process enrollment
uv run python -m pipelines.stage3 --process enrollment
```

Writes `processes/enrollment/outputs/graph.json` and `validation.json`, then prints the
open questions for a human. Exit codes: `0` success, `1` extraction failed (nothing
written), `2` the process or configuration could not be read.

Stage 2 then writes `processes/enrollment/outputs/diagram.bpmn`, which opens in bpmn.io or
Camunda Modeler. Exit codes: `0` success, `1` the layout failed (nothing written), `2` the
process could not be read — including a node attributed to an actor `metadata.yaml` does
not declare, which stage 1 cannot catch because the validator never sees the process config.

Stage 3 then writes `processes/enrollment/outputs/diagram.html`. Exit codes: `0` success,
`1` the page could not be built (bpmn-js is not installed), `2` the process or stage 2's
diagram could not be read. The validation report is optional — a diagram renders whether or
not the questions that came with it are still on disk.

```bash
uv run pytest        # no test touches the network
uv run ruff check .
uv run mypy .        # strict
```

Tests needing the real layouter are marked `requires_node` and skip when Node or
`js/node_modules` is absent; the rest of the suite still runs.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required; no default. |
| `PFG_MODEL_ID` | `claude-opus-4-8` | Model used unless a process overrides it. |
| `PFG_MAX_TOKENS` | `32000` | Output cap per call. A cap, not a reservation. Too low truncates the graph mid-generation. |
| `PFG_MAX_EXTRACTION_ATTEMPTS` | `3` | How many times to ask, including the first attempt. |
| `PFG_LAYOUT_BIN` | pinned install | The `bpmn-auto-layout` executable. Empty uses the version pinned in `js/`. |

Read from the environment or a `.env` file. Stage 2 needs none of them — it calls no model,
so it runs without an API key.

## Adding a process

Copy `processes/enrollment/`, then swap the data — no code changes:

- `metadata.yaml` — machine name (must match the folder), display name, the swimlanes and
  what each one *is*, the default lane, domain shorthand, optional model override.
  `actors` is the complete set of lanes the diagram may use. Descriptions are not
  decoration: a model told only "JCRM" cannot know it is the platform that runs the
  automations, so it cannot place an automated step in that lane. `default_actor` is where
  a box falls when the source never says who — source text routinely describes automation
  in the passive voice ("the PSM is assigned via zip to territory mapping"). It must name
  one of the declared actors.
- `skeleton.json` — the subprocesses a complete description is expected to cover. Drives
  the "is a part missing?" check. `order_hint` is never enforced by the validator — real
  sources routinely run the subprocesses out of order — but stage 2 does use it, as the
  order flow nodes are declared in, which is what sequences the phases across the diagram.
- `inputs/` — the source documents (`.md` or `.txt`), concatenated in filename order.

Actor declaration order is also lane order, top to bottom. Only actors that own at least
one box get a lane, so declaring one the source never uses costs nothing.

## Repo structure

- `ir/` — the typed-graph schema and per-process data models. `models.py` holds the
  Pydantic `Node` / `Edge` / `ProcessGraph` spine, deliberately shape-only so the
  validator's tests can construct broken graphs; its field descriptions are rendered into
  the tool schema the model sees, so they are prompt text.
- `extractors/` — the LLM step. `prompt.py` builds all prompt text; `model.py` is the sole
  Strands/Anthropic boundary; `process.py` runs the retry loop against a protocol rather
  than the SDK; `errors.py` holds the retry taxonomy.
- `validators/` — deterministic checks, no LLM. `predicates.py` holds each check as a pure
  generator of findings; `graph.py` composes them into the structural and resolution
  tiers; `report.py` defines the codes and severities.
- `bpmn/` — stage 2. `semantics.py` decides what each element *is* and the order it is
  declared in; `document.py` writes the semantic XML and no diagram interchange;
  `autolayout.py` is the sole boundary to the layouter. The project contains no JavaScript;
  `js/` at the repo root holds the pinned npm dependencies.
- `render/` — stage 3. `assets.py` holds every file read: the vendored viewer, and the page
  shell; `template.html` is that shell, filled by plain string replacement over comment
  sentinels; `page.py` assembles the page and touches no disk.
- `pipelines/` — per-stage orchestrators. `stage1.py`, `stage2.py` and `stage3.py` each
  compose one run end to end.
- `utils/` — IO helpers and typed environment settings.
- `processes/<name>/` — data only, no code.
- `tests/` — schema, validator, retry loop, IO, prompt, the BPMN mapping and document, the
  page builder, and every orchestrator. Geometry is asserted only in the integration suite,
  against the file the layouter produced. No test drives a browser: the page's tests prove
  what it *says*, and that it *draws* is checked by opening it.
