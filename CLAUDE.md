# Proces Flow Generator

The future state vision of this project is to eventually be able to generate rendered bmpn process flows for patient support program business processes from just user input.

Which stage and which business process are in scope is given in the session prompt.
This file holds only what is true across all stages and processes.

# Repo structure (may be slightly inaccurate)
- `ir/` — the typed-graph schema (Pydantic `Node` / `Edge` / `ProcessGraph`). The spine and single source of truth: the extractor targets it, the validator checks against it, later stages consume it.
- `extractors/` — the LLM step: source text + process config → `ProcessGraph`. The only non-deterministic part.
- `validators/` — deterministic checks, no LLM. Applies the `needs_clarification` tags. The "born valid" gate.
- `pipelines/` — per-stage orchestrators (`stage1.py`, then `stage2.py`, …). Each composes one run: read `processes/<name>/inputs/…` → extractor returns a `ProcessGraph` → validator checks and tags → write `processes/<name>/outputs/…`. Later stages are siblings here, reusing `ir/` and adding their own extract/validate pair.
- `utils/` — thin IO helpers (read input, write output JSON).
- `processes/<name>/` — data only, no code: `inputs/`, `outputs/`, `examples/`, `skeleton.json` (expected subprocesses, drives the "is a part missing?" check), `metadata.yaml` (per-process settings). Adding a process = copy a folder and swap the data; the engine is untouched.
- `tests/` — schema round-trip and validator predicate tests.

## Conventions (mandatory)

The Python skills in `.claude/skills/` are non-negotiable project conventions.
Consult and follow them when writing or reviewing Python: type-safety,
anti-patterns, code-style, testing, design-patterns, linting syntax, configuration, and docstrings.

## Strands

When writing or changing Strands code (agents, tools, structured output, model
providers), consult the Strands MCP (search_docs / fetch_doc) before relying on
memory. Verify APIs against the docs; don't guess.
