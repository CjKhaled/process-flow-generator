# Decisions

Assumptions made while building the conversational stage 1, and the places the repository
differed from the brief it was built from. Each entry says what was found, what was done, and
why — so a later reader can tell a deliberate choice from an accident and knows what to
revisit.

## Where the repository differed from the brief

**The knowledge base has no `README.md`.** `checklist.yaml` and `personas.yaml` both say "see
README" for what a priority and a program fact mean, and the brief says the README defines who
may read each file. It is not in `domain_knowledge/`. The access rules were taken from the brief
and from the header comment of each YAML file, and are enforced in `knowledge/compose.py`: the
navigator reads everything, the interpreter reads topic ids, titles and cues, the extractor
reads lanes, glossary and subprocess names only. Nothing under `domain_knowledge/` was written
or edited. *Revisit when the README exists: check its rules against `compose.py`.*

**Markdown front matter carries `id` and `title` only.** The brief lists `owner` and
`last_reviewed` as well. No file has them, so `FrontMatter` makes both optional rather than
failing every file.

**An empty markdown file is skipped, not rejected.** `agnostic/glossary.md` was a zero-byte
placeholder when the loader was written (it has since been removed). A file that says nothing
is not a reason to refuse to start a conversation; a file with text and no front matter is
still refused, since that is a file somebody started and did not finish.

**`processes/*/inputs/` was removed from the working tree while this was being built.** The
change was not part of this work and was left exactly as found. Eight tests in
`tests/test_stage1.py` read the real enrollment description from that folder, so the
description now also lives in `tests/fixtures/enrollment_description.md` and the fixture
supplies it when the folder carries none. The stage 1 CLI is unchanged and still reads
`inputs/`. *Revisit: if `inputs/` is gone for good, `pipelines/stage1.py`'s CLI and its section
of the README need a decision of their own.*

**`Skeleton` required at least one subprocess.** `ir/skeleton.py` had `min_length=1`, so the
`{"subprocesses": []}` a subprocess flow needs could not be loaded. The limit was dropped. This
is in `ir/`, not `bpmn/` or `render/`; stage 2 already handled an empty list (it simply folds
nothing).

**`GET /processes` is pinned by an existing test to the folders under `processes/`.** Session
processes come from `domain_knowledge/` and are a different list (`enrollment_and_intake`, not
`enrollment`), so they are served by a new `GET /session-processes` and the existing endpoint is
untouched.

**`ModelCall` returns a `ProcessGraph` and has its system prompt baked in.** It is kept exactly
as it is for the one-shot path. The conversation's agents use a new, SDK-free protocol beside
it, `extractors/conversation.py`, whose implementation lives in `extractors/model.py` — still
the only file that imports the SDK.

## Choices the brief left open

**`Session.default_lane` and `Session.requested_focus` are fields the brief did not list.**
The default lane has to be recorded somewhere code can read it, since it changes when the user
names the automation system. `requested_focus` holds a scope the user opened in the page until
the next turn honours it.

**`LedgerEntry.asked_from`.** The brief has a topic nobody answered go "back to
`not_yet_covered`". A topic that was `needs_clarification` or `deferred` before it was asked
again would lose that by the same rule, so the entry remembers what it was and falls back to
it.

**Which open topics become findings.** `open_topic` is raised for a required-priority topic
never settled and for any topic left needing clarification; `deferred_topic` for one put off. A
normal- or low-priority topic nobody reached is not reported: with 98 topics, listing every
question that could have been asked would bury the ones that are actually open.

**A patch update uses null for "unchanged".** A model filling in a tool schema writes explicit
nulls for fields it has no opinion on, so "field present" cannot mean "change it". `NodeFields`
and `EdgeFields` therefore treat null as unchanged and carry a `clear` list for the few fields
that can legitimately be emptied.

**A patch may name an edge by its ends alone.** Edges have no id; an operation names one by
`from_id`, `to_id` and `order`. The order is the part a model gets wrong, so where exactly one
edge joins the two nodes it is taken to be the one meant.

**New nodes are moved into narrative order by code.** A patch can only append, and stage 2 lays
the diagram out by node order, so a step learned on turn nine would otherwise sit at the end of
the graph. `apply_patch` places each added node just after the step that leads to it. Existing
nodes never move.
