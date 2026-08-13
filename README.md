# Process Flow Generator

Turns a written description of a patient support program business process into a typed,
validated process graph — on the way to rendered BPMN diagrams generated from user input
alone.

The hard part is not drawing boxes. It is that real process descriptions are incomplete:
they give the happy path, name three intake channels for one request, and stop before
saying what happens when someone disagrees. So the graph this produces is explicit about
what the source actually supports. Every node is either `stated` or `needs_clarification`,
and every open question is reported for a human rather than quietly invented.

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

## Running it

```bash
uv sync
echo "ANTHROPIC_API_KEY=sk-..." > .env
uv run python -m pipelines.stage1 --process enrollment
```

Writes `processes/enrollment/outputs/graph.json` and `validation.json`, then prints the
open questions for a human. Exit codes: `0` success, `1` extraction failed (nothing
written), `2` the process or configuration could not be read.

```bash
uv run pytest        # no test touches the network
uv run ruff check .
uv run mypy .        # strict
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required; no default. |
| `PFG_MODEL_ID` | `claude-opus-4-8` | Model used unless a process overrides it. |
| `PFG_MAX_TOKENS` | `32000` | Output cap per call. A cap, not a reservation. Too low truncates the graph mid-generation. |
| `PFG_MAX_EXTRACTION_ATTEMPTS` | `3` | How many times to ask, including the first attempt. |

Read from the environment or a `.env` file.

## Adding a process

Copy `processes/enrollment/`, then swap the data — no code changes:

- `metadata.yaml` — machine name (must match the folder), display name, actor vocabulary,
  domain shorthand, optional model override.
- `skeleton.json` — the subprocesses a complete description is expected to cover. Drives
  the "is a part missing?" check. `order_hint` is a layout hint only and is never
  enforced; real sources routinely run the subprocesses out of order.
- `inputs/` — the source documents (`.md` or `.txt`), concatenated in filename order.

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
- `pipelines/` — per-stage orchestrators. `stage1.py` composes one run end to end.
- `utils/` — IO helpers and typed environment settings.
- `processes/<name>/` — data only, no code.
- `tests/` — schema, validator, retry loop, IO, prompt, and orchestration tests.
