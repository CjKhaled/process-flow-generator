# Proces Flow Generator

The future state vision of this project is to eventually be able to generate rendered bmpn process flows for patient support program business processes from just user input.

# Repo structure
- `ir/` — the graph definition. `models.py` (Pydantic Node/Edge/ProcessGraph) is the
  single source of truth: it is the structured-output target AND the Stage 2 contract.
  `skeleton.py` reads a process's expected-subprocess list.
- `extractors/` — the LLM calls: source text + process config -> ProcessGraph.
  The only non-deterministic part of the stage.
- `validators/` — deterministic checker, no LLM. Hard structural rules + soft
  needs_clarification tagging. This is the "born valid" gate and the Stage 2 guarantee.
- `pipelines/` — orchestrator: read input -> extract -> validate -> write output.
  Holds the source-of-truth object in memory.
- `processes/<name>/` — config + data only, no code (inputs/, outputs/, examples/,
  skeleton.json, metadata.yaml).
- `utils/` — thin IO helpers. `tests/` — schema and validator tests.

## Conventions (mandatory)

The Python skills in `.claude/skills/` are non-negotiable project conventions.
Consult and follow them when writing or reviewing Python: type-safety,
anti-patterns, code-style, testing, design-patterns, configuration, and docstrings.

## Strands

When writing or changing any Strands code (agents, tools, structured output,
model providers), consult the Strands MCP (search_docs / fetch_doc) before relying
on memory. Strands changes fast — verify APIs against the docs, do not guess.
