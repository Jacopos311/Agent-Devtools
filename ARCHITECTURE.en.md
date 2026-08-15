# ARCHITECTURE — Agent DevTools (English)

> Architecture document for the `Agent-Devtools` repository (SDK v0.3.0,
> Python ≥ 3.9). It describes **which architectural problem it solves in the
> AI-agents ecosystem** and how it does so, composed into the four requested
> areas: Interception Layer, Tracing Engine, Replay Engine and Fault Injector
> (interpreted as *deterministic mock*). All references are verifiable in
> the source code.

## 1. High-Level Overview — the architectural problem

**The problem.** An AI agent produces an unexpected output. Observability
platforms (Langfuse, Phoenix, Datadog) record *what happened* in aggregate
terms ("average latency", "error rate") and emit fragmented JSON traces.
Reassembling **the final assembled prompt**, **the provenance of every
context block** (memory, doc, tool result), **the memory state at decision
time** and **what changed between a "good" run and a "bad" one** today
means: merging logs, diffing JSON blobs by eye, and guessing. This is
particularly painful for **stale-memory**, **cross-tenant/scope leakage** and
**bad retrieval-selection** bugs, which don't show up in any aggregate.

**Agent DevTools' architectural answer.** It is **Chrome DevTools for AI
agents**: a local-first, first-party debugger that answers a strictly
operational question — *"Why did this run produce this output, and what's
different in the run that didn't?"*. The existential key is an
**append-only event log** (`store.py`) where every event is typed and
ordered by `seq`, and from which **all views are derived at read time**
(`diff.py`, `explain.py`, `memory_view.py`, `scope.py`, `replay.py`).
No export, no shipping data: the backend is a local SQLite file
(`.agent_devtools/trace.db`, env var `AGENT_DEVTOOLS_DB`) and the FastAPI
server (`server/main.py`) reads the same file the SDK writes.

The two central questions the architecture is built around:

1. **What was the causal chain of this run?** (Replay / Prompt / Context /
   Memory / Tools — views derived from the log.)
2. **What diverged from a reference run?** (Behavior Diff with evidence
   chains and assigned likely-causes, in `diff.py`.)

## 2. Core Components

### 2.1 Interception Layer

It is the ingress point for every event. There is no single centralized
"interceptor": interception is **manual and explicit** (primary) and
**framework-adapter based** (secondary). The common intersection of both
paths is `Run._log` in `trace.py:95-96`:

```python
def _log(self, event_type: str, payload: dict) -> None:
    self.store.log_event(self.run_id, event_type, redact(payload))
```

Key points:

- **Redaction at ingestion.** `redact(payload)` (`redaction.py`) masks key
  names (`api_key`, `token`, `password`, …) and known high-entropy shapes
  (`sk-…`, `pk-…`) *before* persistence. It is a courtesy, not a security
  boundary (see §4). This means *no* adapter or event consumer needs to
  worry about sanitization: it's an invariant of the Tracing Engine.
- **Manual path** (`trace.py`, class `Run`). One logging method per event
  kind: `input`, `retrieval`, `context_block`, `prompt`, `tool_call`,
  `memory_read/write/update/delete`, `state_snapshot`, `output`,
  `assert_that`, plus `log_event` as an "escape hatch" for portable formats.
  It's the primary path because it captures what generic traces lose:
  **the final assembled prompt with each context block tagged by its
  provenance** (explicit via `source` of `context_block`).
- **LangChain adapter** (`adapters/langchain.py`, `LangChainTraceHandler`).
  A `BaseCallbackHandler` mapping LangChain callbacks
  (`on_llm_start→prompt.assembled`, `on_llm_end→model.response`,
  `on_tool_start/end→tool.call/result`, `on_retriever_start/end→
  retrieval.query/result`, `on_chain_start→user.input`) to the same typed
  events. It manages standalone runs when no `trace.run()` block is active.
- **Groq adapter** (`adapters/groq.py`). `TracedGroq` wraps a `ChatGroq`
  and records `invoke/ainvoke/batch/stream` → `prompt.assembled` +
  `model.response`; it also manages the run lifecycle for "naked" calls
  (no active `debugger.run()` block), via `debugger._current_run()` /
  `_start_run()` (`debugger.py`).
- **AgentShield adapter** (`adapters/agentshield.py`). Not an LLM-call
  interceptor, but a **consumer of spend/guardrail events** in NDJSON that
  records them in the same log as `agentshield.spend.evaluation`, mapping
  `trace_id→run_id`. It is the ingress for the "external fault/guardrail"
  concept.

### 2.2 Tracing Engine

Built from three tightly-coupled modules:

- **`store.py` — `TraceStore`.** Thread-safe wrapper around a single SQLite
  connection. The schema (`SCHEMA`) has three tables: `runs` (metadata,
  status, `finished_at`), `events` (append-only, `seq` monotonic *per run*
  via `_seq_counters`, real `ts`, `type`, JSON `payload`) and `replays`
  (persisted replay reports). It provides `create_run`/`finish_run`
  (the `finally` of `trace.run()` sets `ok`/`error`), `log_event`, readers
  `get_events`/`get_events_by_types`/`get_run`/`list_runs`,
  `export_fixture`/`import_fixture` (portable `agent-devtools/fixture@1`
  format, `schemas/event.schema.json`) and replay persistence. The default
  path is resolved by `default_db_path()`, which honors `AGENT_DEVTOOLS_DB`
  and otherwise "walks" the directory tree to find an existing DB with at
  least one run — critical since the SDK writes and the server reads the
  same file from different directories.
- **`trace.py` — ingestion entity.** `trace.run()` (context manager) opens
  the `runs` row at `running`, yields a `Run`, and in `finally` calls
  `finish_run` with `ok` or `error` (if the exception propagates).
  `serve()`/`open_ui()` are the zero-config entry points to the debugger.
- **`debugger.py` — `AgentDebugger`.** Zero-config orchestrator: owns the
  `TraceStore`, starts the FastAPI server in a daemon thread
  (`_ensure_server_started`, reuses it if port 4173 is already in use) and
  opens the browser. It holds a non-trivial usability guard:
  `_warn_if_db_mismatch()` checks via `GET /api/health` which DB an already
  running server is serving and warns loudly when it differs from the one
  the SDK is writing to (the #1 cause of "my runs don't show up in the UI").

The data model is **a flat log of typed events**; there is no rigid
"run" schema. This is the core principle of `docs/vision.md`: "store raw
debug events append-only, and derive all views on read", and it's why new
fields (`usage`, `version`, `outcome`, `scope`) can be added without
migrations.

### 2.3 Replay Engine

`replay.py` — class `ReplayEngine`, public method `replay(run_id) ->
ReplayReport` (`replay.py:121`). It is the antidote to agent
non-determinism: **it re-executes a run entirely from its event log, with
no network, no LLM, no user code** (`replay.py:2-7`). It does *not* "re-run
the graph" (unlike `examples/langgraph-memory-agent/verify_traces.py`); it
re-derives from scratch the parts *determined* by the log and checks that
the log is internally consistent. `ReplayReport` (`replay.py:68`) yields
three outcomes:

| status | when |
|---|---|
| `completed` | no contradiction: `summary` says "determinically self-consistent". |
| `diverged` | at least one contradicting event (`evidence` with `severity:"divergence"`): `memory.update` whose `old_value` differs from the reconstructed state, a `memory.read` of a value never written, retrieval ranks non-monotone w.r.t. scores, or a rejected candidate scoring higher than a selected one. |
| `failed` | a recorded `assertion.failed` or `run.status=="error"`. |

The internal `_build_report` (`replay.py:131`) walks events in `seq` order,
keeping a fresh in-memory `memory: dict`, a tool list `pending_tools`
(every `tool.call` must be closed by `tool.result`/`tool.error`), and
accumulates `evidence` with `kind`, `seq`, `severity`, `expected`, `actual`.
The report is **persisted** via `store.save_replay` and served by the API
`POST /api/runs/{run_id}/replay`, `GET .../replays`,
`GET .../replay/{replay_id}/report` (`server/main.py:188-215`). The reason
it is separate from a framework replay is that it works **on any recorded
run**, from UI or HTTP, with no user code.

### 2.4 Fault Injector (interpretation: *deterministic mock*)

> **Note on naming.** The term "Fault Injector" **does not correspond to any
> module/class in the source code** (no `class FaultInjector`, no
> `fault_inject`). It was searched with `search_codebase` and does not exist.
> The component that actually performs the requested *function* — "tracing
> all the way to a deterministic mock" — is the **Fault Injection /
> Deterministic Mock layer** composed of:

1. **Deterministic Replay as a reproducible mock** (`replay.py`). Since
   replay re-executes every event *in isolation*, with fixed inputs and
   touching no network/LLM/code, a `ReplayReport` acts as a **deterministic
   mock** of the run: with the same premises, observed behavior (memory,
   retrieval, tool calls) is reproducible. This is what makes a bug
   "verifiable offline?" and enables regression assertions.
2. **`agent-devtools test`** (`cli.py:_cmd_test`). The CI analogue of
   "fault injection": it imports a fixture (`store.import_fixture`),
   replays its events and **fails (exit code 1) if it contains
   `assertion.failed`**. It's the "inject a controlled failure" equivalent —
   the failing assertion acts as the injected fault — evaluated
   deterministically.
3. **Assertion Engine** (`trace.Run.assert_that` → event
   `assertion.passed`/`assertion.failed`). The point of *injection* of
   structured checks: the agent or an adapter injects an explicit assert
   into the log; the Replay Engine and the `test` CLI lift it back as a fault
   signal.
4. **AgentShield adapter** (`adapters/agentshield.py`): ingress of
   *guardrail/spend* events (`agentshield.spend.evaluation`) — the side
   closest to the "external fault" concept in the log — which can then feed
   the Regression Report (`diff.py:detect_regression`).

In short, "Fault Injector" exists in the codebase as a **scattered set**
(replay engine + test CLI + assertion logging + AgentShield adapter) that
together provide: (a) a reproducible deterministic mock, (b) an injection
point for assertions/faults, (c) a CI runner that turns faults into exit
codes. There is however **no single, dedicated module** — the main
architectural gap to flag (see §4).

## 3. Data Flow — from prompt to (eventual) deterministic mock

The flow is **write-once / read-many** and linear up to the append-only log;
each later stage reads the same SQLite.

```
[agent code / adapter]                         [local disk]              [UI / API / CI]
        │                                           │                          │
  with trace.run(name) ──create_run──> runs: status=running                     │
        │ yield Run                                          │                  │
        │ run.input(prompt) ──_log──> redact() ──log_event──> events: user.input │
        │ run.retrieval(q,results)                              │                │
        │ run.context_block(src="memory",...)                   │                │
        │ run.prompt(system,messages,context)                   │                │
        │ run.tool_call(...) / tool.result                       │                │
        │ run.memory_write/update/delete                         │                │
        │ run.output(response)                                    │                │
        │ run.assert_that(...)                                    │                │
   block end ──finish_run──> runs: status=ok|error                │                │
        │                                                         │                │
   auto_open? ──serve──> AgentDebugger.start()                    │                │
        │                  (uvicorn daemon 127.0.0.1:4173)        ▼                ▼
        │                                          FastAPI server  ──get_store()──> TraceStore (same file)
        │                                          GET /api/runs/{id}
        │                                          GET .../retrieval/explain  ──explain_retrieval()
        │                                          GET .../memory/view ──memory_view() (temporal)
        │                                          GET /api/diff?a=&b= ──diff_runs() (assigned causes)
        │                                          GET /api/regression ──detect_regression()
        │                                          POST .../replay ──ReplayEngine.replay() ──> ReplayReport
        │                                                                                   │
        │                                                                                   ▼
   agent-devtools test fixtures/*.json ──import_fixture──> events replay ──assertion.failed? ──exit 1
```

**Operational step-by-step:**

1. **Open.** `trace.run(agent_name)` calls `store.create_run(run_id,
   agent_name, metadata)` → INSERT into `runs` with `status='running'`,
   initializes `_seq_counters[run_id]=0`. A `Run` is yielded.
2. **Live tracing.** Each `run.<event>(...)` call builds the payload, runs
   it through `redact()` (sanitize at source) and calls `store.log_event`
   → `INSERT INTO events (run_id, seq, ts, type, payload)` with `seq`
   incremented per run (total order guaranteed) and `ts=time.time()`. The
   `retrieval` and `context_block` methods are designed to **preserve
   provenance**: `context_block(source=...)` and the retrieval `outcome`/
   `denied`/`reason` fields are exactly the data `diff.py` consumes.
3. **Close + serve.** In `finally`, `store.finish_run(run_id, status)`
   updates `finished_at`/`status`. If `auto_open`, `trace.serve()` →
   `AgentDebugger.start()` → `_ensure_server_started()` checks whether
   127.0.0.1:4173 is free; if so it launches Uvicorn in a daemon thread on
   `agent_devtools.server.main:app`, otherwise reuses the running server
   (and `_warn_if_db_mismatch` checks it serves the same DB). The SDK and
   server share one SQLite file: `agent-devtools serve` and the SDK resolve
   `default_db_path()` (or `AGENT_DEVTOOLS_DB`) the same way — but not
   always (see §4).
4. **Read / derived views.** The UI (SPA in `server/static/`:
   `index.html`/`app.js`/`style.css`) calls the REST API. Every endpoint
   calls `get_store()` (a shared global instance) and reads events; views
   are derived on demand: `explain_retrieval` (`explain.py`) pairs
   `retrieval.query`+`retrieval.result` and emits human reasons;
   `memory_view` (`memory_view.py`) derives the temporal memory state;
   `diff_runs` (`diff.py`) produces sections, narration, assigned likely
   causes and evidence chains; `detect_scope_mismatches`
   (`scope.py`) checks cross-tenant leakage. Nothing is materialized at
   write time: adding a view needs no migrations.
5. **Deterministic mock / replay.** `POST /api/runs/{run_id}/replay` →
   `ReplayEngine(store).replay(run_id)` → `_build_report` walks events in
   `seq` order, rebuilds memory from scratch and checks consistency →
   `ReplayReport` (status completed/diverged/failed + `evidence`). The
   report is saved in `replays` and shown in the **Replay** tab.
   Separately, `agent-devtools test` (`cli.py`) imports a JSON fixture,
   replays its assertions and turns `assertion.failed` into `exit(1)` —
   the CI branch of the "deterministic mock": a fault recorded in a run
   becomes a repeatable CI failure.

One thing not to miss: **context provenance** (`source` of `context_block`,
`outcome`/`denied` of retrieval, `scope` metadata) is what `diff.py` uses
to *explain* a divergence (e.g. "a stale memory block appears verbatim in
the bad run's answer") and not a decorative field. That is why the
Interception Layer is manual-first rather than a generic JSON bridge.

## 4. Design Trade-offs & Challenges — the critical points

- **Local-first vs shareability.** The file-based SQLite DB is the source of
  the zero-config simplicity ("open your browser, runs appear"), and is also
  the #1 real-world usability bug: `AgentDebugger._warn_if_db_mismatch`
  exists because the SDK and the server can resolve `default_db_path()`
  differently (scripts launched from `examples/`, server from root) and,
  until a server is listening, the client can't detect the mismatch. The
  `_walk_parents` + subdirectory search (`store.py:58-99`) mitigates but
  does not eliminate it. A conscious trade-off: no Postgres/hosted mode
  (roadmap), but a latent foot-gun.
- **Flat events vs rigid schema.** The "append-only + read-time views"
  principle (`docs/vision.md`) is strong on extensibility (new `usage`/
  `version`/`outcome`/`scope` fields without migrations) and on not losing
  framework-specific detail. The cost: event consumers must parse defensively
  (see `explain_retrieval` using `.get()` everywhere) and there's no DB-level
  constraint — a typo'd event type (`retrieval.result`) is invisible until
   read. The "`agent-devtools test` has no shipped fixtures" limitation
  (`README.md:588`) is a consequence: without example fixtures, event-model
  consistency is upheld by code alone.
- **Redaction is honest, not a security boundary.** `redact()`
  (`redaction.py`) and its application in `Run._log` hide key names and
  known-shape tokens. But it's not a DLP: it won't catch arbitrary
  alphanumeric secrets pasted into a prompt, and nothing is encrypted. The
  server has no auth (known limit, `README.md:592`) and reads the same file
  any process tool can open. Coherent with "local debug", but stated plainly.
- **Heuristic vs truth.** Two pillars (Behavior Diff `diff.py` and
  Retrieval Explanation `explain.py`) are *deliberately* heuristic. The Diff
  doesn't prove the cause, it *indicates* it ("intentionally heuristic, not
  a proof", `diff.py:6-12`); retrieval explain *infers* reasons when none
  were recorded. It's a perceived-vs-real trade: it avoids forcing every
  event into a rigid schema (which would drop detail) but asks the user to
  separate "debug hypothesis" from "truth". The Replay Engine is instead
  *truth*: `completed` really means "internally consistent". The pair
  (Replay = truth / Diff = hint) is the product's spine.
- **The nomadic role of "Fault Injector".** As §2.4 explains, there is no
  single component. The "deterministic mock" is an *emergent effect* of
  Replay + the `test` CLI. Operationally this means: a team can't "inject a
  fault" (e.g. simulate a failing tool, or an empty retrieval) into a real
  run through one API — it must record the events into the log by hand (or
  write an adapter). This is an **explicit architectural gap**: the project
  targets *reactive* debugging (why a bug happened) and *regressive* CI, not
  *proactive* fault simulation. A dedicated `faults.py` with controlled
  injection would be a natural extension, not foreseen.
- **Performance / SQLite concurrency.** SQLite under a single `self._lock`
  serializes reads and writes. Plenty for interactive local debugging; it
  wouldn't scale to many concurrent writers — but that's not the use case
  (one agent = one writer).
- **`AgentDebugger.stop()` is a no-op** for the Uvicorn daemon thread, so
  the server doesn't shut down until the process exits (`README.md:589`).
  The design *assumes* the server lives for the whole debug session and is
  never cycle-restarted.

## 5. Video Talking Points (5 minutes)

A 5′ oral script aligned with `ARCHITECTURE.md`. Minutes are indicative
("slow pace" → focus on 3 strong ideas).

| Min | What to say (aloud) | Slide/file ref |
|-----|---------------------|----------------|
| 0:00–0:30 | **Hook — the real problem.** "Observability platforms tell you *how slow* your agent is. DevTools asks *why* an agent said the wrong thing. We don't want another dashboard; we want the three lines of the trace that explain the bug." | README.md:4,22-31 |
| 0:30–1:30 | **Core idea: append-only event log + read-time views.** "Everything lives in one SQLite file. Nothing is exported. The server reads the same file. Why does that matter? I can add an `outcome` field to retrieval and the UI just shows it — no migrations, no rigid schema dropping detail." | docs/vision.md:48-55, store.py:SCHEMA |
| 1:30–2:30 | **The thing everyone misses: context provenance.** "Agents fail because they read stale memory. The log distinguishes `context.block(source='memory')` and records injection order. The Behavior Diff pastes the stale value into the bad run's answer and it jumps at you: 'this stale value is in the reply'. That's what a generic JSON trace loses." | trace.py:144-150 (`context.block`), diff.py:8-11 |
| 2:30–3:45 | **Deterministic replay = offline mock.** "The Replay Engine re-executes every event *with no network, no LLM, no user code*. If it says `completed`, the bug is reproducible offline; if `diverged`, the log is internally contradictory (e.g. a memory.update against a value never written — the same stale-memory bug, now *proven*)." | replay.py:2-7, replay.py:131 (`_build_report`), 68-94 |
| 3:45–4:45 | **From debugging to CI on one model.** "The same events that let me say 'it's the stale memory' from the CLI become a CI failure: `agent-devtools test` imports a fixture, replays it, and fails (exit 1) on `assertion.failed`. The Assertion Engine (`run.assert_that`) is the fault injector — one log powers interactive debugging and automated regression." | cli.py:23-48, trace.py:191-193 |
| 4:45–5:00 | **Honest close.** "Limits: redaction isn't security, Diff is heuristic, server has no auth, and there's no *single* 'Fault Injector' component — it's an effect of Replay+test. But it answers one question nobody else poses directly: 'why this run, not that one?'" | README.md:588-592, §2.4/§4 |

---

## File map (operational summary)

```
packages/python-sdk/agent_devtools/
├── trace.py          # Interception Layer (manual) + tracing entry (Run, trace.run, serve/open_ui)
├── store.py          # Tracing Engine (TraceStore, append-only SQLite, fixture I/O)
├── redaction.py      # Interception Layer — ingestion-time sanitization (redact)
├── debugger.py       # Tracing Engine — zero-config orchestrator (AgentDebugger, server lifecycle, _warn_if_db_mismatch)
├── replay.py         # Replay Engine + Deterministic Mock (ReplayEngine, ReplayReport)
├── diff.py           # Behavior Diff: assigned likely-causes + evidence chains (diff_runs, detect_regression)
├── explain.py        # Retrieval Explanation (explain_retrieval)
├── memory_view.py    # Temporal memory view (memory_view) — derived at read time
├── scope.py          # Cross-tenant leakage detection (detect_scope_mismatches)
├── cli.py            # Fault/Mock layer CLI: serve + test (fixture replay → exit code)
├── adapters/
│   ├── langchain.py  # Interception Layer — LangChain callback bridge (LangChainTraceHandler)
│   ├── groq.py       # Interception Layer — TracedGroq wrapper
│   └── agentshield.py# Fault layer — spend/guardrail event ingress (NDJSON → log)
└── server/           # FastAPI debug server + static UI; read API over the same SQLite
    └── main.py
```






