

https://github.com/user-attachments/assets/170840ee-a694-409f-b38d-b605683143bb





# agent-devtools

**Chrome DevTools for AI agents.** Instrument a run, then see exactly why
it produced the output it did.

```python
from agent_devtools import trace

with trace.run("refund-agent") as run:
    run.input(user_message)
    run.retrieval(query, results)
    run.context_block(source="memory", key="pricing", content=text)
    run.prompt(system=system_prompt, messages=messages)
    run.tool_call(name="lookup_price", args={"plan": "pro"}, result={"price": "$29/mo"})
    run.output(response_text)
```

```bash
agent-devtools serve
```

Open the local UI and you get: the final prompt the model actually saw,
every context block tagged with where it came from, the retrieval
candidates and their scores, the memory lifecycle, every tool call --
and a **Diff** tab that takes a good run and a bad run and tells you, in
plain language, what changed and which change is the likely cause.

This is not another observability dashboard. It's local-first, and it's
built around one question: *why did my agent behave this way?*

## 60-second Groq demo (zero-config, free)

The quickest way to see the Dashboard live -- no credit card, no local
model. Uses [Groq](https://groq.com) (free tier) with
`llama-3.3-70b-versatile`, starts the local server, opens the browser,
and traces an interactive chat with memory.

```bash
pip install "agent-devtools[groq]"      # or: pip install agentscope langchain-groq

export GROQ_API_KEY="your_free_key"     # free key: https://console.groq.com/keys

python demo.py
```

That's it. The Dashboard opens automatically at
`http://127.0.0.1:4173`, and every message, memory read, context block,
prompt, and model response is traced live.

If `GROQ_API_KEY` isn't set, the script prints clear instructions with
where to get a free key.

> In this repo, `python demo.py` uses the local SDK automatically. If you
> prefer a manual install from source, run
> `pip install -e "packages/python-sdk[groq]"` first.

### Non-interactive alternative

```bash
pip install -e packages/python-sdk
cd examples/stale-memory-bug
python good_run.py
python bad_run.py
agent-devtools serve
```

Open `http://127.0.0.1:4173`, click **Diff**, compare `good-run-1` vs
`bad-run-1`. You'll see a stale memory entry outrank a newer document in
retrieval, get injected into the prompt instead, and leak into the
final answer -- with a callout that names it as the likely cause. See
[`examples/stale-memory-bug/README.md`](examples/stale-memory-bug/README.md)
for the full walkthrough.

## Why instrument instead of importing a trace?

Every agent framework emits a different trace shape, so a JSON-import-first
tool spends your time writing adapters instead of debugging, and it rarely
captures the one thing that matters most: the exact final prompt, with
context tagged by provenance. Instrumenting a run directly, where the bug
actually lives, is a handful of lines (above) and gives you everything
immediately. JSON stays supported as a **fixture format** -- for bug
reports, GitHub issues, and CI regression tests -- but it's an escape
hatch, not the front door. See [`docs/vision.md`](docs/vision.md) for the
full reasoning.

## What's in this repo right now

This is a sharp, complete debugging loop, not a scaffold with empty
panels. It is intentionally **not** the entire long-term roadmap from
`docs/vision.md` -- framework adapters, a JS SDK, and a Langfuse/Phoenix
bridge are real, valuable, and not yet built. Here's exactly what exists:

| Layer | What's built |
|---|---|
| **Python SDK** (`packages/python-sdk`) | `trace.run(...)` context manager; `input`, `retrieval`, `context_block`, `prompt`, `tool_call`, `memory_read/write/update/delete`, `state_snapshot`, `output`, `assert_that`; best-effort secret redaction before anything is persisted; fixture export/import. |
| **AgentDebugger** | Zero-config entry point: `AgentDebugger()` owns the store, starts the local server, opens the Dashboard automatically, and exposes `create_groq_llm(...)` / `run(...)`. |
| **LangChain adapter** | `LangChainTraceHandler` — a `BaseCallbackHandler` that maps chain/LLM/tool/retriever callbacks to agent-devtools events (`user.input`, `prompt.assembled`, `model.response`, `tool.call`, `tool.result`, `retrieval.query`, `retrieval.result`). |
| **Groq adapter** | `TracedGroq` / `create_groq_llm(...)` — full `langchain-groq` support out of the box (`llama-3.3-70b-versatile` default); wraps `ChatGroq` so every message and response is traced, with a clear error message when `GROQ_API_KEY` is missing. |
| **Local trace store** | Append-only SQLite event log (`.agent_devtools/trace.db` by default); every UI tab is a derived view computed at read time. |
| **Debug server** (FastAPI) | REST API for runs, replay, prompt, context, retrieval, memory, tools, fixture export, and diff. |
| **DevTools UI** | Replay, Prompt, Context, Retrieval, Memory, Tools, and Diff tabs, served locally, no build step. |
| **Diff engine** | Compares two runs across input / retrieval / context / prompt / tools / memory / output, with a heuristic "likely cause" callout when a changed value shows up in the final answer. |
| **CLI** | `agent-devtools serve`, `agent-devtools test fixtures/*.json` for CI (fails the build on any `assertion.failed` event). |
| **Example** | `examples/stale-memory-bug` -- a runnable, realistic good-run/bad-run pair. `examples/langchain-integration` -- a LangChain chain wired to `LangChainTraceHandler`. |

**Not built yet** (see Roadmap): more framework adapters (LangGraph,
OpenAI Agents SDK, CrewAI, LlamaIndex), a Langfuse/Phoenix trace bridge,
a JS/TS SDK, a hosted/Postgres mode, and a `devtools.instrument(agent)`
auto-wrapper for arbitrary agent objects. None of these are needed to
get value out of the tool today -- they're where it grows next.

## Repo layout

```
.
├── packages/
│   └── python-sdk/
│       └── agent_devtools/
│           ├── trace.py          # the trace.run() context manager
│           ├── store.py          # append-only SQLite trace store
│           ├── diff.py           # the Behavior Diff engine
│           ├── redaction.py      # secret redaction before persistence
│           ├── cli.py            # `agent-devtools serve` / `test`
│           ├── debugger.py       # AgentDebugger zero-config entry point
│           ├── adapters/         # framework adapters (LangChain, Groq, ...)
│           └── server/           # FastAPI debug server + static UI
├── demo.py                       # 60-second Groq demo (zero-config)
├── examples/
│   ├── stale-memory-bug/         # the 60-second demo
│   └── langchain-integration/    # LangChain adapter example
├── schemas/
│   └── event.schema.json         # portable fixture format
└── docs/
    └── vision.md                 # why this is a debugger, not a dashboard
```

## Event model

Everything is one append-only stream of typed events per run:

```
user.input · retrieval.query · retrieval.result · context.block
prompt.assembled · tool.call · tool.result
memory.read · memory.write · memory.update · memory.delete
state.snapshot · model.response · assertion.passed · assertion.failed
```

Every tab in the UI, and the diff engine, is a view derived from this
log -- nothing is thrown away because a panel didn't ask for it up
front.

## CI: debug assertions

```python
with trace.run("refund-agent") as run:
    ...
    run.assert_that("no stale pricing mentioned", "$19" not in answer,
                     details="answer must not reference the pre-July price")
```

Export the run as a fixture (`GET /api/runs/{id}/fixture`, or
`store.export_fixture(run_id)`) and check it in CI:

```bash
agent-devtools test fixtures/*.json
```

This replays each fixture and fails the build if any
`assertion.failed` event is present.

## Roadmap

1. ~~Reposition around causal debugging, define the append-only event
   schema~~ -- done, this repo.
2. ~~Python SDK, local SQLite store, fixture export~~ -- done.
3. ~~DevTools MVP: Replay / Prompt / Context / Retrieval / Memory /
   Tools / Diff~~ -- done.
4. ~~One excellent example: the stale-memory bug~~ -- done.
5. Deepen Behavior Diff: smarter causal ranking, prompt token diffing,
   multi-run comparison.
6. Framework adapters: LangChain done (`LangChainTraceHandler`). Groq done
   (`TracedGroq` / `create_groq_llm`, zero-config demo in `demo.py`).
   Next: LangGraph, then OpenAI Agents SDK, CrewAI, LlamaIndex.
   Langfuse/Phoenix trace import as a bridge, not a competitor.
7. Debug assertions as a first-class CLI workflow for CI (`agent-devtools
   test` exists today for fixtures; richer assertion types and reporting
   are next).

## License

MIT. See `LICENSE`.
