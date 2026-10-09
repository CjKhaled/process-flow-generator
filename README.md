# Process Flow Generator

Turns a conversation about a patient support program business process into a proper BPMN
process diagram — swimlanes, decisions, subprocesses and all.

You describe how the process runs. It drafts the flow, asks about what you left out a few
questions at a time, redraws after every answer, and when you are done hands you a BPMN file
and a page for the main flow and for each subprocess.

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

## Stage 1 — the conversation

```
you describe the process ─► a first draft of the flow appears
                              │
        ┌─────────────────────┘
        ▼
   up to three questions ─► you answer ─► the flow is updated ─┐
        ▲                                                      │
        └──────────────────────────────────────────────────────┘
                              │ nothing important left, or you choose to finish
                              ▼
               the main flow and each subprocess ─► stages 2 and 3, unchanged
```

One pasted description is rarely the whole process, so stage 1 is a conversation. It drafts
the flow from what you wrote, asks about what is missing a few questions at a time, redraws
the flow after every answer, and at the end hands the finished flows to stages 2 and 3.
After every reply it stops and waits for you: nothing moves until you answer.

The questions are informed by a knowledge base of how programs like this are usually
organised. That is useful and it is dangerous, so the rule the whole design is built around
is this: **what the tool knows about other programs decides what it asks, and never what it
draws.**

It holds because the work is split between three narrow AI steps, each seeing only what it
needs:

- **The interpreter** reads your message against what was asked. It reports which topics you
  addressed, which roles and systems you named, and what you corrected. It never sees the
  flow.
- **The extractor** turns your new statements into changes to the flow, and nothing else. It
  is never shown the knowledge base. It gets your words, the roles you have named, and a
  glossary.
- **The navigator** chooses the next questions and writes the reply. It is the only one that
  reads the knowledge base, and it cannot change the flow.

Around them is ordinary code, which owns everything that has to be the same on turn twenty
as on turn two: what you said, which topics are covered, which roles exist, where the
discussion is focused. No AI step is trusted to remember any of it.

### Every step cites your words

Each box and each branch records the statements it came from and the exact words in them, and
code looks those words up. A box whose quote is not in the statement it names is rejected
and the extractor is asked again. Click any step in the page and you see the sentence it
rests on, and which turn you said it in.

Where you described only one outcome of a decision — "if the prescriber agrees, the patient
proceeds" — the other is closed with a marked placeholder rather than guessed. That is what
keeps the flow drawable after every turn, and it is also what the next question is about.

### Every change gets checked

After each answer the extractor proposes changes to the flow, and before any of them is
shown they go through about twenty automatic checks, which sort into two piles.

**Malformed** means the flow is broken and could not be drawn, or says something you did
not: two boxes with the same name, an arrow pointing at a box that doesn't exist, a decision
with only one way out, a box nothing leads to, a box with no lane — and a box that quotes
words you never said. These are mechanical mistakes. The AI is told exactly what's wrong
and asked to fix that and nothing else, up to three attempts. **If it never succeeds, the
flow stays as it was** and your answer is applied on the next turn. You are told so.

**Needs a human** means the flow is fine but something is still open. These are *never* sent
back to the AI. Asking it to "fix" an ambiguity is asking it to invent something, which is
the one failure this whole design exists to prevent. They become the next questions.

You might reasonably ask why any of this is needed when the AI is already filling in a
strict form. The form guarantees each box and each arrow is individually well-shaped — right
fields, sensible values. It can't check anything involving *two* boxes at once, or a box
against what you actually said, because it only ever sees one thing at a time. Every check
above is about how things relate to each other, which is why they have to live somewhere
else.

### Nobody picks a client

You choose a process and nothing else. Role names, system names and facts about the program
are learned from what you say. Until you name the system that does the automated work, steps
nobody is named for sit in a lane called `System (unconfirmed)`, and the tool asks.

### One flow, sliced

A session holds one flow. A subprocess — off-label review, duplicate handling, the two
missing-information outreach flows — is a tag on some of its steps, not a second copy. The
main view shows each as one box; opening one shows its steps as a flow of their own, cut out
by code. They cannot disagree, because there is only one of each step.

### Finishing

When nothing important is left, or when you choose to finish, the page lists what is still
open in each flow. You answer more, or accept. On accepting, each flow is written out in the
same layout a hand-made process folder has, and stages 2 and 3 run on it unchanged. You get
a BPMN file and a page per flow.

The chat then steps aside and the finished diagrams take its place: one tab per flow, each
showing stage 3's own page, so rearranging it in Edit mode and the open-questions panel work
exactly as they do in the downloaded file. **Back to requirements** returns to the chat.
Finishing is not a seal — answer something there and the session reopens; the diagrams stay
on show, marked as out of date, until you finish again and they are redrawn.

*In the code: `agents/` holds the three AI steps and their prompts, `session/` the
conversation around them, `knowledge/` the loader for `domain_knowledge/`, `validators/` the
checks, and `ir/models.py` the form being filled in. [technical.md](technical.md) has the
detail, and [docs/DECISIONS.md](docs/DECISIONS.md) the assumptions made building it.*

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
resize what needs more room
      │
      ▼
colour it in
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

Three things get special treatment.

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
another box, the change is abandoned and the library's version is kept.

Start and end points are widened in the same pass, for the same kind of reason: they're drawn
as horizontal ovals, and the layout library sized them as small squares because that's how
BPMN normally draws them.

### Colour goes into the file, not into the web page

Start and end points come out red, and the folded-up subprocess boxes purple — pale enough
that black text on them stays readable.

Those colours are written into the diagram file itself rather than applied by the web page.
It would have been less work to do it in the page's stylesheet, but then the colours would
only exist *in our page*: a colleague opening the file in Camunda or any other BPMN tool
would see plain black and white. Putting them in the file means every tool shows the same
diagram. (An earlier version of this project did use the stylesheet, and was wrong to.)

Only those two get colour. Colouring everything would say nothing — the point is to make the
start, the ends and the handed-off work findable at a glance.

*In the code: `bpmn/semantics.py` decides what each thing is and folds the subprocesses,
`bpmn/document.py` writes the file, `bpmn/autolayout.py` calls the layout library,
`bpmn/decisions.py` resizes the diamonds and the start/end points, and `bpmn/colors.py`
colours them.*

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
in orange, and the questions are listed beside the diagram rather than left in a file
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

The toolbar on the left offers only the pieces these diagrams are made of — a start, an end,
a step, a decision, a folded-up subprocess and a note. The diagram library ships fifteen
tools covering the whole of BPMN, and most of them would let you add something no later part
of the pipeline understands.

### A note on how the page is built

The page needs the diagram library *plus* this project's own additions — the custom shapes,
the trimmed toolbar, the switch that makes Edit mode possible. Those have to be compiled
together into a single file, which is what `npm run build --prefix js` does. So a fresh
clone needs three commands, not two:

```bash
uv sync
npm ci --prefix js
npm run build --prefix js
```

Forgetting the last one is the most likely reason stage 3 fails on a new machine, and the
error says so.

*In the code: `render/page.py` assembles the page, `render/template.html` is the shell, and
`js/src/` holds the browser modules — `renderer.js` for the custom shapes, `palette.js` for
the toolbar, `editGate.js` for the Edit switch.*

## The service and the page

```
the page                         the service
┌──────────────────┐  here's my answer      ┌────────────────────┐
│ chat             │ ─────────────────────► │ run one turn       │
│ the live flow    │                        │                    │
│ where each step  │  how's it going?       │ save the session   │
│ came from        │ ◄───────────────────── │ after every turn   │
└──────────────────┘  still working / done  └────────────────────┘
```

A turn is three AI calls and takes longer than a web request is allowed to stay open. So the
page doesn't wait for an answer: it sends yours, gets an acknowledgement back, and checks in
every second or so. That's also what lets it tell you *which* step is running rather than
just spinning.

The page has two views. **Requirements** is where the conversation happens, in three parts:
the chat on the left, the flow in the middle with a tab for each subprocess, and on the right
either where the selected step came from or how much of the process is covered.
**Diagrams** appears once a session has been finished, and shows the finished BPMN pages.

**What you type is saved**, in a session file on the server, after every turn. That is what
lets a conversation be picked up again, and it is also a reason to keep the service
somewhere private: there is no login, no rate limit, and every turn costs real AI calls.

*In the code: `api/sessions.py` is the endpoints, `api/app.py` the application around them,
`frontend/` the page.*

## Running it

```bash
uv sync
npm ci --prefix js && npm run build --prefix js               # the layouter and the diagram viewer
npm ci --prefix frontend && npm run build --prefix frontend   # the page
echo "ANTHROPIC_API_KEY=sk-..." > .env
uv run --group api uvicorn api.app:app
```

Then open `http://127.0.0.1:8000/`. Sessions are written under `sessions/`, one folder each,
with the finished flows beside the session file in `sessions/<id>/flows/<flow>/`.

Or without the page, in a terminal:

```bash
uv run python -m session.cli start --process enrollment_and_intake --input description.md
```

That runs the first turn and drops into a chat: the reply and its questions, then your
answer, then a line on the flow and one per flow on coverage. `/focus <flow>` moves the
discussion, `/state` prints the flow, `/close` lists what is open, `/accept` writes the final
diagrams, `/quit` leaves. Every turn is saved, so `resume --session <id>` picks one back up.

Stages 2 and 3 run by themselves at the end of a session. They can also be run by hand on any
flow folder — a finished session's, or one of the examples under `processes/`:

```bash
uv run python -m pipelines.stage2 --process enrollment
uv run python -m pipelines.stage3 --process enrollment
```

Stage 2 writes `outputs/diagram.bpmn`, which opens in bpmn.io or Camunda Modeler. Exit codes:
`0` success, `1` the layout failed (nothing written), `2` the folder could not be read. A
step attributed to someone `metadata.yaml` never listed is not an error: it gets a lane of
its own, drawn after the listed ones.

Stage 3 writes `outputs/diagram.html`. Exit codes: `0` success, `1` the page could not be
built (the viewer is not installed or not built), `2` the folder or stage 2's diagram could
not be read. The validation report is optional — a diagram renders whether or not the
questions that came with it are still on disk.

### What it tells you

Every entry point — the service, the session CLI, the three stages — logs to the console and
to `logs/app.log`: each step of a turn, what the interpreter read, which coverage topics
moved and what moved them, why the extractor was or was not called, which questions were
kept or dropped and why. Beside it, `logs/trace.jsonl` has one line per model call with
everything: the system prompt, the prompt, the response or the error, the model, the
duration and the token counts.

Both files are **overwritten every time the process starts**. They are for debugging the
run in front of you, not a history. And both contain whatever was typed in, which is why
`logs/` is not committed.

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
| `ANTHROPIC_WORKSPACE_ID` | — | Only for an API key that is not scoped to a workspace: the workspace to use, sent as a header on every request. |
| `PFG_MODEL_ID` | `claude-opus-4-8` | Model every agent runs on, unless its own setting below names another. |
| `PFG_MAX_TOKENS` | `32000` | Output cap per call. A cap, not a reservation. Too low truncates the graph mid-generation. |
| `PFG_MAX_EXTRACTION_ATTEMPTS` | `3` | How many times the extractor is asked per turn, including the first attempt. |
| `PFG_INTERPRETER_MODEL_ID` | `PFG_MODEL_ID` | The interpreter's model. The role that can run on a faster, cheaper one. |
| `PFG_EXTRACTOR_MODEL_ID` | `PFG_MODEL_ID` | The patch extractor's model. |
| `PFG_NAVIGATOR_MODEL_ID` | `PFG_MODEL_ID` | The navigator's model. |
| `PFG_DOMAIN_DIR` | `domain_knowledge` | The knowledge base. Read-only at run time. |
| `PFG_SESSIONS_DIR` | `sessions` | Where sessions are written. Gitignored. |
| `PFG_LOG_LEVEL` | `DEBUG` | How much the application says. `INFO` is what happened and why; `DEBUG` adds every prompt and response in full. |
| `PFG_LOG_DIR` | `logs` | Where `app.log` and `trace.jsonl` are written. Gitignored. |
| `PFG_LAYOUT_BIN` | pinned install | The `bpmn-auto-layout` executable. Empty uses the version pinned in `js/`. |
| `PFG_ALLOWED_ORIGIN` | `*` | Comma-separated origins the page may call from, when it is served from somewhere other than the service. |
| `PFG_MAX_SOURCE_CHARS` | `20000` | Longest description, or answer, accepted. |

Read from the environment or a `.env` file. Stages 2 and 3 need none of them — they call no
model, so they run without an API key. Neither does the service at startup: it loads the key
when a turn begins, so a misconfigured instance answers `/health` and explains itself on the
first turn rather than crash-looping.

## Adding a process

A process is a folder under `domain_knowledge/`. No code changes: the service offers every
folder that holds a readable `process.yaml`.

- `process.yaml` — what the process is: where it starts and ends, what is in and out of
  scope, and **the subprocesses that should exist**. That list is the only part of the
  knowledge base that directs the flow: it says which subprocesses the extractor may tag,
  which are drawn as one box, and which get a flow of their own. It also names the persona
  whose lane takes work nobody is named for, the usual order of lanes, and when a flow
  counts as covered.
- `checklist.yaml` — the coverage topics: what a complete description would settle. Each has
  a scope (the main flow or a subprocess), a priority, cue words, and an opening question.
  A topic can depend on a fact about the program — no nurse program, no nurse topics — and
  can name the subprocess its decision hands off to.
- Markdown topic files — how programs of this kind are usually organised. Only the navigator
  reads these, to ask better questions. Nothing in them ever reaches the flow.

`domain_knowledge/agnostic/` is shared by every process: the personas a lane can be, the
glossary, and background on patient support programs.

`tests/test_domain_knowledge.py` checks what the files must agree on between themselves — a
topic that hands off to a subprocess that does not exist, a program fact with no screening
question — and runs over whatever is on disk, so a new process is covered by existing.

**The flow folder.** What a finished session writes for each flow, and what stages 2 and 3
read: `metadata.yaml` (the lanes, in order, with what each one is, and the default lane),
`skeleton.json` (the subprocesses drawn as one box, and the lane each box sits in), and
`outputs/`. Nobody writes these by hand any more; close-out composes them from the session.
The two folders under `processes/` are examples in that layout, kept for running stages 2
and 3 by themselves and for their tests.

## Repo structure

- `ir/` — the typed-graph schema and per-process data models. `models.py` holds the
  Pydantic `Node` / `Edge` / `ProcessGraph` spine, deliberately shape-only so the
  validator's tests can construct broken graphs; its field descriptions are rendered into
  the tool schema the model sees, so they are prompt text.
- `extractors/` — the model boundary. `model.py` is the sole Strands/Anthropic import, and
  every call goes through one traced wrapper there; `conversation.py` is the protocol the
  agents depend on instead of the SDK; `errors.py` holds the retry taxonomy; `prompt.py`
  holds the conventions that make a graph valid, which the extractor's prompt quotes.
- `domain_knowledge/` — the knowledge base the conversation runs on. Data only, read-only at
  run time: personas, glossary, and per process a definition, a coverage checklist and
  topic files.
- `knowledge/` — reads it. `schemas.py` is the shape of every file; `loader.py` loads one
  process's worth; `compose.py` decides what each agent is told, which is where "knowledge
  drives questions, never content" is enforced.
- `agents/` — the three AI steps: `interpreter.py`, `extractor.py`,
  `navigator.py`, and their system prompts as markdown in `prompts/`.
- `session/` — the conversation around them, all deterministic. `models.py` is the session
  file; `orchestrator.py` the turn pipeline; `statements.py`, `patch.py`, `ledger.py`,
  `candidates.py` and `focus.py` the steps between the agents; `slicing.py` and `views.py`
  the subprocess flows and what the page draws; `closeout.py` the hand-off to stages 2 and
  3; `store.py` where sessions are kept; `cli.py` the terminal chat.
- `frontend/` — the page: Vite, React and TypeScript, built to `frontend/dist/` and served
  at `/`. A separate Node project from `js/`.
- `validators/` — deterministic checks, no LLM. `predicates.py` holds each check as a pure
  generator of findings; `graph.py` composes them into the structural and resolution
  tiers; `report.py` defines the codes and severities; `session_checks.py` holds the checks
  only a conversation can make — evidence, lanes, scopes.
- `bpmn/` — stage 2. `semantics.py` decides what each element *is* and the order it is
  declared in; `document.py` writes the semantic XML and no diagram interchange;
  `autolayout.py` is the sole boundary to the layouter; `decisions.py` redraws each gateway
  and widens each event afterwards, and is the only geometry this project owns; `colors.py`
  writes fill and stroke into the file so every BPMN tool shows the same diagram.
- `render/` — stage 3. `assets.py` holds every file read: our built bundle, the diagram
  library's stylesheets, and the page shell; `template.html` is that shell, filled by plain
  string replacement over comment sentinels; `page.py` assembles the page and touches no
  disk.
- `js/` — the npm dependencies, and `src/`: the browser modules bundled into the page by
  esbuild. `renderer.js` draws the custom shapes, `palette.js` trims the toolbar,
  `editGate.js` is the Edit switch, and `viewer.js` ties them together. Built output goes to
  `js/dist/` and is not committed.
- `api/` — the service. `sessions.py` is every endpoint and the worker that runs turns;
  `app.py` builds the application around it and serves the page, with the model and the
  layouter as arguments so it can be tested without either.
- `pipelines/` — `stage2.py` and `stage3.py`: each stage as a command over one flow folder.
  Stage 1 has no entry here; it is `session/`.
- `utils/` — typed environment settings, logging and the model trace, and a JSON writer.
- `processes/<name>/` — example flow folders, data only: `enrollment` and
  `coverage_determination`.
- `tests/` — the schema, both validators, the knowledge base's own consistency, each
  deterministic step of a turn, whole sessions run turn by turn with the three agents
  scripted, the service, close-out, the BPMN mapping and document, and the page builder. Geometry is asserted only in the
  integration suite, against the file the layouter produced. No test drives a browser: the
  page's tests prove what it *says*, and that it *draws* is checked by opening it.
