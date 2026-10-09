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

## Not verified

**No turn has been run against a real model.** The key in `.env` is rejected by the API
(`401 invalid x-api-key`), so the two real-model checks in the build plan — `session.cli start`
on the enrollment description, and a ten-turn CLI session — could not be made. Everything
else is exercised: the whole turn pipeline runs end to end in `tests/test_session_loop.py`
with the three agents scripted, and close-out runs against the real layouter and the real
viewer bundle in `tests/test_closeout_integration.py`. What that leaves unproven is the part
only a model can show: whether the three prompts produce patches that pass the evidence check
first time, lanes the way the brief expects them, and questions in the right voice. *Do this
first with a working key:*
`uv run python -m session.cli start --process enrollment_and_intake --input tests/fixtures/enrollment_description.md`

## The agents

**The navigator's knowledge is cached through a message, not the system prompt.** Strands'
`AnthropicModel` (1.51) sends the system prompt as a plain string, so a cache point placed in it
is dropped; one inside a message is turned into `cache_control`. `StrandsConversationFactory`
therefore sends `cached_context` as the opening exchange of the conversation, ending in a cache
point. The role and style rules stay in the system prompt; the knowledge files and the checklist
are the cached block.

**The navigator has no `get_node` tool.** The brief made it optional, conditional on tools and
structured output working reliably together. That was not worth establishing for an MVP: the
navigator's graph summary already carries each open step's detail, which is what the tool would
have been asked for.

**The interpreter gets one repair turn.** The brief says an interpreter failure rejects the
turn. A response that merely missed a required field is cheap to fix and expensive to bounce
back to a person, so a schema failure earns one repair turn in the same conversation; a second
failure rejects the turn.

**An answer's statements are checked against the message.** After turn 1 the interpreter splits
the message itself. Statement text is what quotes are verified against, so a statement whose
`raw_text` is not found in the user's message is replaced by the whole message rather than
trusted.

**Restatement faithfulness is a prompt rule, not a check.** A quote may be matched against a
statement's restatement, and the restatement is written by the interpreter. Code cannot tell a
faithful restatement from one that adds a fact, so this is the one place a model's wording can
reach the evidence check unverified. The page shows a statement's own text beside any quote, so
a reader can see the difference. *Revisit: require that every quote taken from a restatement
also be supported by the raw answer plus the question text.*

**The extractor is not called when nothing was described.** A quick reply ("Not sure yet", "Not
part of our process") and a message the interpreter reads as being about the session itself
describe no process. Calling the extractor on them would spend a model call to be told nothing
changed. Statements queued from a failed turn, and corrections, always earn a call.

**A screening answer settles its screening topic.** When the interpreter reports a program
fact but no status for the topic that sets it, code marks that topic `present` (fact true) or
`confirmed_absent` (fact false), so the same question is not asked again.

**A subprocess the user says does not exist takes its topics with it.** When every topic that
hands off to a subprocess is `confirmed_absent`, the topics inside it become `not_applicable`,
exactly as a denied program fact would make them. The brief only describes facts doing this.
Without it, a program with no off-label review would be asked seven questions about one.

**A subprocess's topics rank last until the conversation reaches it.** "High-priority gaps in
other scopes" sit at rank 6, but only for a subprocess that has steps in the flow or whose
hand-off topic the user has spoken to. Before that they sit at rank 7.

**`propose_close` is accepted only when nothing at rank 6 or above can still be asked.**
Otherwise a navigator could end a session with high-priority topics untouched.

**A refused request aborts the turn whichever agent hit it.** The brief's failure table gives
the navigator a fallback, and separately says `ModelUnavailableError` aborts the turn. The
second wins: a fallback reply after a refused request would save a turn whose patch came from
a model that is no longer reachable, and the next turn would fail anyway.

**Mid-conversation, `missing_required_subprocess` is dropped.** `validate` raises it for every
subprocess with no node, which early in a session is all four, every turn. The ledger already
tracks what has not been reached.

## Slicing and close-out

**The final main BPMN ends each path at its subprocess box.** Stage 2's fold drops edges
leaving a collapsed box and prunes what only they led to; that is existing behaviour and was
not changed. The live view keeps those edges, as the brief asks, so the two differ: in the page
a subprocess box flows on to the next step, in the final main diagram it does not. Each
subprocess's own diagram shows where it returns to.

**A slice's exit into an outside terminal carries that terminal's open question.** Where a
subprocess path runs into a terminal on the main flow, the synthesised exit copies the label,
and also the status and detail, so a `needs_clarification` outcome is still marked in the
subprocess's own diagram.

**A start node is never part of a slice**, whatever its tag, and a subprocess nothing leads
into yet is entered at its first step in graph order.

**Close-out reports accepted items.** Accepting an open item at close-out does not remove it
from `validation.json`: it is still open, and the final page lists it. Acceptance only stops
the conversation asking.

**Subprocess flows declare the default lane even when nothing sits in it.** `ProcessConfig`
requires `default_actor` to be a declared actor. Stage 2 draws no lane for an actor nothing is
attributed to, so this costs a line of `metadata.yaml` and nothing in the diagram.

## The service and the page

**`frontend/` is a second Node project.** `CLAUDE.md` said nothing ran under Node but the
layouter and the `js/` build, and that a build needing a config file meant something was in
the wrong language. The brief asks for a Vite, React and TypeScript page, which has both. It
was kept apart from `js/` rather than merged into it, so the existing build stays as trivial
as it was, and `CLAUDE.md` now says so.

**The hosted image does not build `/app`.** Deployment changes were out of scope, so the
`Dockerfile` and the Pages workflow are untouched. `/app` is mounted only when
`frontend/dist/` exists; without it the service runs exactly as before. *Revisit when the
conversation is to be hosted: add the two `npm` lines to the `Dockerfile`, and decide where
`sessions/` lives, since a container's disk is not durable.*

**Turns run on a pool of four workers.** The brief asks for one background worker queue like
`api/runs.py`, and also allows different sessions to run concurrently. A single worker would
make every session wait for every other. Per-session serialisation is what matters and is
enforced separately, by refusing a second turn while one is in flight.

**A session left mid-turn by a restart is reported as failed.** The turn's work was on a copy
and is gone, so the stored session is exactly as it was before the turn. `GET /sessions/{id}`
says so, where otherwise the page would poll a turn nobody is running.

**`item_key` on `POST /messages`.** The brief's close-out view has an "Answer" action that
returns to the chat with that item as the pending question. The message endpoint takes the
item's key, and the orchestrator makes it the pending question before the interpreter reads
the answer.

**The first view of a flow fits its opening steps, not the whole flow.** A process of a dozen
steps fitted whole is too small to read. After that the viewport is left alone, so an answer
that adds a step does not throw away where the reader had panned to.

**The page was checked by driving it, not by a test.** No test in this project drives a
browser, and that was kept. A full scripted session — start, live flow, rationale, a
subprocess tab, an answer, close-out, downloads — was run through the built page in a
headless browser against the real service with scripted agents, with no console errors.

## Credentials

**`ANTHROPIC_WORKSPACE_ID` is optional and sent as a header.** An API key that is not scoped
to a workspace is refused with a `400` unless each request carries `anthropic-workspace-id`.
The setting is named without the `PFG_` prefix because, like the key beside it, it is the
provider's own variable and not this project's. Both the one-shot path and the conversation
build their client through one function, so they cannot come to authenticate differently.

## Reversed after the first real runs

**A lane nobody declared is no longer an error, anywhere.** The first real one-shot run was
cancelled because the model put a step in a lane `metadata.yaml` did not list. Two things
changed.

*Stage 2.* `bpmn/semantics.py::lane_order` draws such a lane after the declared ones and logs
it, where it used to raise. This is the one edit made under `bpmn/`, which the original brief
put off-limits; it was asked for directly. The check contradicted the extraction prompt, which
tells the model to use the source's own wording for someone outside the list.

*The conversation.* The brief's `unknown_lane` structural code is removed. A lane the
extractor uses that the session has not learned is added as `proposed` with no persona, and
the existing rank 2 lane question asks the user what it is. The extractor's prompt now says
to use the statement's own name for someone not listed, where it said never to.

What is lost: a lane the model genuinely invented is now drawn, and in the one-shot path
nothing asks about it — it is only logged. In the conversation the user is asked.

**Logging is verbose by default and overwrites itself.** `PFG_LOG_LEVEL` defaults to `DEBUG`
and `logs/app.log` and `logs/trace.jsonl` are truncated on every start, by request: the
project is being debugged far more than it is being run. *Revisit before this is hosted:* the
trace holds everything users type and every prompt in full, the default level is too loud
for a shared service, and a file that is overwritten on restart is no record of anything.

**Strands' console printing is off on both paths.** The one-shot agent used the default
callback handler, which is where `Tool #1: ProcessGraph` came from. Both agents are now built
with none, and the application's own lines say what was called, how long it took and what it
cost.

**Polling stays.** A webhook was raised as more scalable. It does not apply here: a webhook
is the server calling a URL the client hosts, and the client is a browser tab. The push
alternatives for a browser are server-sent events or a WebSocket, both of which need a
heartbeat to survive a host that drops quiet connections, and a polling fallback when the
stream drops. Not changed.

## The one-shot path is removed

The original stage 1 — one pasted description, one extraction, no questions — is gone, by
decision. The conversation was first built beside it, at `/app`, because the brief said to
leave the page at `/` alone; that left two front doors on one server, and the one people
landed on was the old flow with no conversation in it.

Removed: `POST /runs`, `GET /runs/{id}`, the old `GET /processes`, `api/pipeline.py`,
`api/runs.py`, `pipelines/stage1.py`, `pipelines/site.py`, `extractors/process.py`, the
one-shot model adapter and prompt builders, `render/page.py::build_app` with the landing form
and polling script in `render/template.html`, `utils/io.py::read_source`,
`ir/process_config.py::list_processes`, `ProcessConfig.model_id`, and their tests. Stages 2
and 3 are untouched and still run as commands over a flow folder.

Changed with it: the page is served at `/`; `GET /session-processes` is now `GET /processes`;
`GRAPH_FILENAME` and `REPORT_FILENAME` live in `ir/process_config.py`; the `Dockerfile` and
the Pages workflow build `frontend/` instead of the old static page.

**Entries above that this makes obsolete.** "`GET /processes` is pinned by an existing test",
"`ModelCall` returns a `ProcessGraph`", "The hosted image does not build `/app`", and the
remarks about what the one-shot path does with an unlisted lane or with Strands' console
printing all describe a path that no longer exists. They are left as written, as a record of
why things were built the way they were at the time.

**`processes/` stays** as two example flow folders for running stages 2 and 3 by themselves
and for their tests. Nothing lists or serves them.

**The hosted copy is not yet fit to use.** The Pages workflow now publishes the conversation
and the image builds it, but a session is a file on the instance's disk, a free instance
loses its disk on restart, there is no login, and the log level defaults to `DEBUG`. *Decide
where sessions live before pointing anyone at a hosted copy.*

## The diagrams view

**The finished diagrams are shown in a frame, not redrawn.** After a session is finished the
page shows each flow's `diagram.html` in an `<iframe>`. Rebuilding the BPMN viewer inside the
React page would have meant a second copy of Edit mode, the questions panel and the custom
shapes to keep in step with stage 3. The frame costs one endpoint that serves the file
without a download header.

**A finished session can be reopened.** The brief ended a session at `complete`. Going "back
to requirements" would be little use if nothing could be said there, so a message to a
finished session returns it to `probing`. What was accepted as open stays accepted. The
diagrams from the last finish stay on show and are marked out of date until it is finished
again; they are not deleted, because a reader comparing before and after wants the before.

**Finishing twice in a row is refused.** `/close` and `/accept` on a session that is already
complete answer `409`: nothing has been said, so the result would be the same files.

**A flow that no longer has steps keeps its old folder on disk.** If a reopened session
removes a subprocess's only steps and is finished again, that subprocess is no longer listed
or shown, but its folder from the earlier finish is not deleted.
