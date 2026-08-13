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
- `pipelines/` — per-stage orchestrators (`stage1.py`, then `stage2.py`, …). Each composes one run: read `processes/<name>/inputs/…` → extractor returns a `ProcessGraph` → validator checks and tags → write `processes/<name>/outputs/…`. A graph failing the structural tier is never written, so later stages may assume anything in `outputs/` is well formed. Later stages are siblings here, reusing `ir/` and adding their own extract/validate pair.
- `utils/` — `io.py` (read the input text, write output JSON) and `settings.py` (typed environment settings, loaded through a function rather than at import so the suite runs without an API key).
- `processes/<name>/` — data only, no code: `inputs/` (source documents), `outputs/` (generated `graph.json` and `validation.json`), `skeleton.json` (expected subprocesses, drives the "is a part missing?" check), `metadata.yaml` (display name, actors, glossary, optional model override). Adding a process = copy a folder and swap the data; the engine is untouched.
- `tests/` — schema round-trip, validator predicates, the retry loop against a fake model, IO, prompt assembly, and stage-1 orchestration end to end. No test touches the network.

## Conventions (mandatory)

The Python skills in `.claude/skills/` are non-negotiable project conventions.
Consult and follow them when writing or reviewing Python: type-safety,
anti-patterns, code-style, testing, design-patterns, linting syntax, configuration, and docstrings.

ALWAYS update relevant document for READMEs, docstrings, comments, etc when making edits so these do NOT go stale!

## Strands

When writing or changing Strands code (agents, tools, structured output, model
providers), consult the Strands MCP (search_docs / fetch_doc) before relying on
memory. Verify APIs against the docs; don't guess.
