# Agent DevTools

**Chrome DevTools for AI Agents. Understand exactly why your AI agent behaved that way.**

Most AI observability tools tell you what happened. Agent DevTools tells you **why**.

https://github.com/user-attachments/assets/170840ee-a694-409f-b38d-b605683143bb

![Agent DevTools Demo](assets/demo.gif)

---

## The Problem

Your AI agent said something unexpected. Why?

- Which memory influenced the answer?
- Which retrieval won?
- Which tool changed the output?
- What prompt did the LLM actually receive?

Agent DevTools answers those questions **in real-time**.

---

## Quickstart

Zero-config. Free. 60 seconds to a live dashboard.

```bash
pip install "agent-devtools[groq]"
export GROQ_API_KEY="your_groq_key"
python demo.py
```

That's it. The Dashboard opens automatically at `http://127.0.0.1:4173` — every message, memory read, context block, prompt, and model response traced live.

---

## The Killer Feature: Behavior Diff

A dashboard tells you a number changed. A debugger tells you **why**.

Run the same agent twice — once good, once bad — and the Diff engine walks input, retrieval, context, prompt, tools, memory, and output to surface the **likely cause** in plain language.

```bash
cd examples/stale-memory-bug
python good_run.py
python bad_run.py
agent-devtools serve
```

Open the **Diff** tab. See a stale memory entry outrank a newer document, get injected into the prompt, and leak into the final answer — with a callout naming it as the cause.

No more diffing two JSON blobs by hand.

---

## What You Get

| Tab | What it shows |
|---|---|
| **Replay** | The full run, step by step |
| **Prompt** | The exact final prompt the LLM saw |
| **Context** | Every context block, tagged by provenance |
| **Retrieval** | Candidates and their scores |
| **Memory** | The full memory lifecycle |
| **Tools** | Every call, args, and result |
| **Diff** | Good run vs bad run → likely cause |

**Local-first.** Everything stays in an append-only SQLite log (`.agent_devtools/trace.db`). Nothing leaves your machine.

**Framework adapters.** LangChain and Groq work out of the box. More coming.

---

## Roadmap

- [x] Python SDK + local SQLite store
- [x] DevTools UI: Replay / Prompt / Context / Retrieval / Memory / Tools / Diff
- [x] LangChain + Groq adapters
- [x] CI debug assertions (`agent-devtools test fixtures/*.json`)
- [ ] Smarter causal ranking, prompt token diffing, multi-run comparison
- [ ] LangGraph, OpenAI Agents SDK, CrewAI, LlamaIndex adapters
- [ ] Langfuse/Phoenix trace bridge
- [ ] JS/TS SDK

---

## Architecture

```
.
├── packages/
│   └── python-sdk/
│       └── agent_devtools/
│           ├── trace.py          # trace.run() context manager
│           ├── store.py          # append-only SQLite trace store
│           ├── diff.py           # Behavior Diff engine
│           ├── redaction.py      # secret redaction before persistence
│           ├── cli.py            # agent-devtools serve / test
│           ├── debugger.py       # AgentDebugger zero-config entry point
│           ├── adapters/         # LangChain, Groq, ...
│           └── server/           # FastAPI debug server + static UI
├── demo.py                       # 60-second Groq demo
├── examples/
│   ├── stale-memory-bug/         # good-run/bad-run Diff demo
│   └── langchain-integration/    # LangChain adapter example
├── schemas/
│   └── event.schema.json         # portable fixture format
└── docs/
    └── vision.md                 # why this is a debugger, not a dashboard
```

### Event model

Everything is one append-only stream of typed events per run:

```
user.input · retrieval.query · retrieval.result · context.block
prompt.assembled · tool.call · tool.result
memory.read · memory.write · memory.update · memory.delete
state.snapshot · model.response · assertion.passed · assertion.failed
```

Every UI tab and the diff engine is a derived view over this log — nothing is thrown away.

### Instrument a run

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

### CI: debug assertions

```python
run.assert_that("no stale pricing mentioned", "$19" not in answer,
                details="answer must not reference the pre-July price")
```

```bash
agent-devtools test fixtures/*.json
```

Fails the build on any `assertion.failed` event.

---

## License

MIT. See `LICENSE`.
