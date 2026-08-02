# Vision

**agent-devtools is Chrome DevTools for AI agents.** Given a run, it shows
the exact chain of causes behind the output: user input, retrieved
memory, prompt assembly, injected context, tool calls, the model
response, state changes -- and how all of that differs from a prior run.

## What this is not

It is not an observability platform. It does not compete with
Langfuse, Phoenix, or any hosted tracing product, and it is not trying
to give you aggregate latency/cost dashboards. Those are good tools for
a different question ("is my system healthy on average"). This tool
answers a different, narrower question, well:

> Why did *this* run produce *this* output, and what's different about
> the run that didn't?

## Why manual instrumentation is the primary path

Generic JSON/trace import is kept as a portable fixture format -- useful
for bug reports, GitHub issues, and CI regression tests -- but it is
deliberately not the main way to get value out of this tool. Every
agent framework emits a different shape of trace, so a JSON-first tool
spends its users' time writing adapters instead of debugging. Worse,
generic traces rarely capture the one thing that matters most: the
final assembled prompt, with each piece of context tagged by where it
came from.

Instrumenting a run directly, in the code where the bug actually lives,
is a few lines:

```python
from agent_devtools import trace

with trace.run("refund-agent") as run:
    run.input(user_message)
    run.retrieval(query, results)
    run.context_block(source="memory", key="pricing", content=text)
    run.prompt(system=system_prompt, messages=messages)
    run.tool_call(name="lookup_price", args={...}, result={...})
    run.output(response_text)
```

Then `agent-devtools serve` opens a local UI against the same SQLite
file. No trace export, no shipping data anywhere.

## The append-only event log

Everything is stored as a flat, append-only log of typed events. The
UI's tabs (Replay, Prompt, Context, Retrieval, Memory, Tools, Diff) are
all *derived views* over that log, computed at read time. This is
deliberate: framework-specific detail doesn't get lost by forcing every
event into one rigid shape up front, and new views can be added later
without a migration.

## The killer feature: Behavior Diff

A dashboard tells you a number changed. A debugger tells you why. Given
a good run and a bad run of the same agent, the diff engine walks
input, retrieval, context, prompt, tools, memory, and output, and
surfaces the differences most likely to explain the change in output --
for example, a stale value from a memory entry that shows up verbatim
(or as a matching number) in the bad run's answer, but not the good
run's.

This is intentionally a heuristic, not a proof. It's meant to point you
at the three lines of a trace worth reading closely, instead of forcing
you to diff two JSON blobs by eye.

## What's deliberately not in this first cut

A Langfuse/Phoenix trace bridge, a JS/TS SDK, and a hosted/Postgres
mode are all reasonable additions -- once the SDK, the event model, and
the diff engine have proven themselves on real agents. Building those
first, before the core debugging loop is solid, is how a memory
visualizer turns into "yet another dashboard." See `README.md` for the
current scope and the roadmap for what comes next.

## Framework adapters

The primary integration path remains manual instrumentation -- it captures
the one thing that matters most: the exact final prompt, with context tagged
by provenance. That said, framework adapters that bridge into the
append-only event log from the framework's own callback system are the
natural next step, and LangChain is the first of those:

```python
from agent_devtools import trace
from agent_devtools.adapters import LangChainTraceHandler

with trace.run("my-agent") as run:
    handler = LangChainTraceHandler(run=run)
    chain.invoke({"question": "..."}, config={"callbacks": [handler]})
```
