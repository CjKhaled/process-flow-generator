# Process Flow Generator

Turns a written description of a patient support program business process into a proper
BPMN process diagram — swimlanes, decisions, subprocesses and all — from the prose alone.

**[Try it](https://cjkhaled.github.io/process-flow-generator/)** — pick a process, paste a
description, and watch it be read, checked and drawn. The pipeline runs on a free Render
instance that sleeps when idle, so the first run of the day waits about a minute for it to
wake; the page starts that wake-up as soon as it loads.

## The problem this solves

Drawing boxes is the easy part. The hard part is that real process descriptions are
incomplete. They give the happy path and stop. They name three ways a request can arrive as
though it were three processes. They say what happens when the prescriber agrees and never
say what happens when they don't.

A tool that quietly fills those gaps is worse than useless, because the invented steps look
exactly like the real ones. So this one doesn't. Every box it produces is marked either
**stated** — the source supports this — or **needs clarification**, meaning a human has to
settle it. The open questions come out in a list beside the diagram instead of being guessed
at.

The other thing it insists on is that **every box belongs to somebody**. Actors are
swimlanes: a step sits in the lane of whoever performs it, a decision in the lane of whoever
decides, an end state in the lane that owns the outcome. Where the description never says
who — and real documents say "the record is created" constantly — the box falls to a
default lane the process declares, rather than floating unattached.

Three stages, run in order. Only the first one uses AI; the other two are ordinary code that
produces the same result every time.

*In the code: [technical.md](technical.md) walks through all three in full detail.*

## Stage 1 — reading the description

```
what the process is   ─┐
which parts fold up   ─┼─► instructions ─► AI ─► first draft
the written description┘                          │
                                                  ▼
                                          automatic checks
                                            │            │
                                       malformed       sound
                                            │            │
                                       ask again    the diagram data
                                       (up to 3x)   + open questions
```

Three things go in.

**What the process is.** Written once by hand, and reused for every run: the list of people
and systems involved, each with a sentence saying what they are, plus a glossary of the
shorthand the industry uses. This matters more than it sounds. Told only that "JCRM" exists,
the AI cannot know it's the platform that runs the automations, so it cannot work out that
an automated step belongs in that lane. The sentence is what makes the decision possible.

**Which parts fold up.** Also written by hand: the named chunks of work the process hands
off to — off-label review, duplicate handling. These are listed once rather than discovered
each time, because they're the same whoever writes the description up. Stage 2 draws each as
a single box.

**The written description.** The prose itself. Locally this is a file; on the hosted version
it's whatever you paste into the form.

Those become a set of instructions, and the AI is asked to fill in a strict form rather than
write freehand — so the answer comes back as structured data, not as text to be
interpreted.

### Then it gets checked

The draft is put through about a dozen automatic checks, which sort into two piles.

**Malformed** means the diagram data is broken and could not be drawn: two boxes with the
same name, an arrow pointing at a box that doesn't exist, a decision with only one way out,
a box that nothing leads to, a box that leads nowhere, a box with no lane. These are
mechanical mistakes. The AI is told exactly what's wrong and asked to fix that and nothing
else, up to three attempts. **If it never succeeds, nothing is saved at all** — a broken
diagram is worse than no diagram.

**Needs a human** means the diagram is fine but the description left something open. These
are *never* sent back to the AI. Asking it to "fix" an ambiguity is asking it to invent
something, which is the one failure this whole design exists to prevent. They're saved
alongside the diagram and shown to the reader.

You might reasonably ask why any of this is needed when the AI is already filling in a
strict form. The form guarantees each box and each arrow is individually well-shaped — right
fields, sensible values. It can't check anything involving *two* boxes at once, because it
only ever sees one at a time. Every check above is about how things relate to each other,
which is why they have to live somewhere else.

*In the code: `extractors/` builds the prompt and runs the retry loop, `validators/` holds
the checks, `ir/models.py` is the form being filled in.*

## Stage 2 — drawing it

```
the diagram data
      │
      ▼
decide what each thing is  ─  step, decision, end, lane
      │
      ▼
fold up the subprocesses
      │
      ▼
write the file (no positions yet)
      │
      ▼
work out where everything goes
      │
      ▼
make the decisions readable
      │
      ▼
a real BPMN diagram
```

No AI here at all. The same data always produces exactly the same drawing.

A BPMN file is really two files in one: a list of *what the things are* and how they connect,
and a separate list of *where each one sits on the page*. This stage writes the first list
itself and hands it to an off-the-shelf library to work out the second. That library is worth
depending on because it understands BPMN specifically — it knows a lane restricts where a box
can go, that a decision's branches belong near it, and that an arrow shouldn't be run through
an unrelated box.

Because the positions are somebody else's job, the only influence this stage has on how the
final picture looks is **the order it lists things in** — the library breaks ties that way. So
the sorting is doing real work, not tidying.

Two things get special treatment.

### Subprocesses fold into one box

Anything the process hands off — off-label review, duplicate handling — is drawn as a single
box, and its internal steps aren't drawn at all. The box goes where the first of its steps
would have gone, in the lane the process declares for it.

**Nothing comes back out of one of these boxes.** At this level of detail the path is over
once it reaches one, so arrows leaving it are dropped, and anything only those arrows led to
goes with them. Whatever the main flow still reaches is untouched. The one exception is a
start, which is always drawn even if it was tagged as belonging inside a subprocess — a
process with no visible beginning isn't a process, and seeing it there is how you notice the
tagging was wrong.

Nothing is actually lost: the saved data still has every step, and a question raised about a
hidden step is pointed at the box that swallowed it.

### Decisions carry their question

A decision in a flowchart is usually drawn as an empty diamond with the question floating
somewhere nearby. When there are twenty of them, matching each question to its diamond is
work the reader shouldn't have to do. And the layout library, having no better idea, puts one
question above its diamond and the next one below.

So after everything is positioned, each diamond is redrawn: made bigger, with its question
moved inside it, and the arrows leaving it labelled **Yes** and **No**. The branches are also
fanned out to leave from different corners, rather than all sharing one line.

Which branch is the "yes" comes from the AI in stage 1, not from guessing at render time. A
diagram that's confidently backwards is worse than one that's wordy, and guessing from the
wording works right up until it meets "unless the prescriber declines".

This redrawing is careful about what it touches. If moving an arrow would send it through
another box, the change is abandoned and the library's version is kept. Nothing but the
decisions is altered.

*In the code: `bpmn/semantics.py` decides what each thing is and folds the subprocesses,
`bpmn/document.py` writes the file, `bpmn/autolayout.py` calls the layout library, and
`bpmn/decisions.py` redraws the diamonds.*

## Stage 3 — making it viewable

```
the BPMN diagram  ─┐
the open questions ┼─► one HTML file you can just open
the viewer         ┘
```

The result is a single self-contained page. The diagram viewer, its styling, the drawing and
the questions are all baked into the one file, so nothing is loaded from anywhere when you
open it. That's deliberate: the page gets opened from whatever folder someone happens to
point at, and any link to a neighbouring file breaks the moment they choose a different one.
The cost is about 730 KB a page, which is why it's generated rather than kept in the repo.

This is where the open questions finally become visible. Every box that has one is outlined
in dashed amber, and the questions are listed beside the diagram rather than left in a file
next to it. Select a question and it finds the box; select a marked box and it finds the
question. A diagram with nothing outstanding says so.

The question list sits in a panel that floats *over* the drawing rather than beside it, so
opening and closing it never resizes the diagram or shifts a single box.

### You can rearrange it, but you can't keep it

There's an **Edit** button. Turn it on and the diagram becomes fully editable — drag boxes
around, rename them, add or delete things, re-route arrows. **Reset** puts everything back
where the generator had it.

None of it is saved. Reload the page and you get the generated diagram again.

That's on purpose rather than an unfinished edge. Think of it as a scratchpad: somewhere to
push the boxes around until the process makes sense to you, not somewhere to correct
mistakes and keep the correction. Making a correction stick would mean feeding it back into
the underlying data and re-running the checks, which is a much bigger piece of work and
isn't here.

One consequence worth knowing: the open questions are worked out before you start editing
and never recalculated. If you delete a box that had a question against it, the question
stays in the list, now pointing at nothing. The page says as much while you're editing.

*In the code: `render/page.py` assembles the page, `render/template.html` is the shell —
where the diagram's appearance is decided, and where editing is switched on and off.*

## The hosted demo

```
the web page                    the server
┌──────────────────┐  here's a description   ┌────────────────────┐
│ pick a process   │ ──────────────────────► │ run all three      │
│ paste a          │                         │ stages in memory   │
│ description      │  how's it going?        │                    │
│                  │ ◄────────────────────── │ nothing saved      │
└──────────────────┘   still working / done  └────────────────────┘
```

Stages 1 and 2 can't run in a browser — one needs an API key, the other needs a program
installed on a server. So the page is static and the actual work happens elsewhere.

A run takes a minute or two, which is longer than a web request is allowed to stay open. So
the page doesn't wait for an answer: it asks for the work to start, gets a ticket back, and
checks in every so often. That's also what lets it tell you *which* stage is running rather
than just spinning.

The server hands back exactly what the offline page contains, so from the moment there's a
result, the hosted page and the downloadable one are the same page.

**Nothing you type is saved.** No run writes anything to the repository — what someone pastes
in belongs to them.

The demo is deliberately unguarded: no rate limit, no password, and every run costs a real AI
call. That's a decision that only holds while the link isn't widely shared.

```bash
uv run python -m pipelines.site --api-base https://pfg-api.onrender.com   # the page
uv run --group api uvicorn api.app:app --reload                          # the service
```

*In the code: `api/pipeline.py` runs the three stages in memory, `api/runs.py` tracks work in
progress, `api/app.py` is the web endpoint.*

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
| `PFG_ALLOWED_ORIGIN` | `*` | Hosted demo only: comma-separated origins the page may call from. |
| `PFG_MAX_SOURCE_CHARS` | `20000` | Hosted demo only: longest description accepted. |

Read from the environment or a `.env` file. Stage 2 needs none of them — it calls no model,
so it runs without an API key. Neither does the service at startup: it loads settings when
a run begins, so a misconfigured instance answers `/health` and explains itself on the
first run rather than crash-looping.

## Adding a process

Copy `processes/enrollment/`, then swap the data — no code changes:

- `metadata.yaml` — machine name, display name, the swimlanes and
  what each one *is*, the default lane, domain shorthand, optional model override.
  Nothing enforces that the machine name matches the folder, but every id in the generated
  BPMN file is built from it, so a copied folder with an unedited name produces a diagram
  whose internals name the process it was copied from.
  `actors` is the complete set of lanes the diagram may use. Descriptions are not
  decoration: a model told only "JCRM" cannot know it is the platform that runs the
  automations, so it cannot place an automated step in that lane. `default_actor` is where
  a box falls when the source never says who — source text routinely describes automation
  in the passive voice ("the PSM is assigned via zip to territory mapping"). It must name
  one of the declared actors.
- `skeleton.json` — the stretches of work the process **hands off**, each of which stage 2
  draws as one collapsed box. Not a coverage checklist for the whole process: the running
  narrative belongs to no subprocess and is drawn step by step, so listing a main-flow phase
  here would make it vanish into a box. Drives the "is a part missing?" check as well.
  `actor` is the lane the box is drawn in, and must be one of the declared actors — it is
  stated rather than derived, because the lane that owns a subprocess is frequently not the
  lane performing most of its steps. There is no ordering field: the order they are listed
  in sets the order they appear in prompts and reports, and nothing else. It is never
  enforced, because real sources run the subprocesses in any order, and it places nothing —
  the diagram draws each box where its first step appeared.
- `inputs/` — the source documents (`.md` or `.txt`), concatenated in filename order. Used
  by the command line only; the hosted demo extracts from whatever is pasted into the form,
  and reads the two files above from disk regardless.

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
  `autolayout.py` is the sole boundary to the layouter; `decisions.py` redraws each gateway
  afterwards, and is the only geometry this project owns. The project contains no JavaScript;
  `js/` at the repo root holds the pinned npm dependencies.
- `render/` — stage 3, and the hosted page. `assets.py` holds every file read: the vendored
  viewer, and the page shell; `template.html` is that shell, filled by plain string
  replacement over comment sentinels; `page.py` assembles both pages from one payload and
  touches no disk.
- `api/` — the hosted demo's service. `pipeline.py` composes stages 1–3 in memory from the
  same functions the CLI calls; `runs.py` holds runs in flight; `app.py` is the HTTP
  surface, with the model and the layouter as constructor arguments so it can be tested
  without either.
- `pipelines/` — orchestrators. `stage1.py`, `stage2.py` and `stage3.py` each compose one
  run end to end; `site.py` builds the hosted page.
- `utils/` — IO helpers and typed environment settings.
- `processes/<name>/` — data only, no code.
- `tests/` — schema, validator, retry loop, IO, prompt, the BPMN mapping and document, the
  page builder, the service, and every orchestrator. Geometry is asserted only in the
  integration suite, against the file the layouter produced. No test drives a browser: the
  page's tests prove what it *says*, and that it *draws* is checked by opening it.
