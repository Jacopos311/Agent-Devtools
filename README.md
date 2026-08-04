# Agent DevTools

**Chrome DevTools for AI Agents. Understand exactly why your AI agent behaved that way.**

Most AI observability tools tell you what happened. Agent DevTools tells you **why**.

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

### Retrieval Explanation

The **Retrieval** tab now explains *why* each candidate was selected or rejected instead of only showing numbers.

For every retrieved memory it shows:

- **Original query** and **rewritten query** (when available)
- **Metadata filters** applied
- **Embedding model**
- **Similarity score** and **reranker score**
- **Threshold** and **reranker threshold**
- **Selected / rejected** state
- **Human-readable reason** for the decision

Example reasons:

> Selected because similarity score 0.91 exceeded the threshold 0.80 and reranker score 0.85 passed the reranker threshold 0.50.
>
> Rejected because similarity score 0.52 was below the threshold 0.80.
>
> This chunk was excluded because metadata filters removed it.
>
> Selected despite similarity score 0.75 being below the threshold 0.80 because the reranker score 0.85 passed the reranker threshold 0.50.

To enrich retrieval traces, pass query metadata to `run.retrieval(...)`:

```python
run.retrieval(
    query=user_question,
    results=results,
    rewritten_query="current Pro plan price",       # after query rewriting
    filters={"source": ["doc", "memory"]},          # metadata filters applied
    embedding_model="text-embedding-3-small",        # embedding model used
    threshold=0.80,                                  # similarity cutoff
    rerank_threshold=0.50,                           # reranker cutoff
)
```

Per-result metadata can override query-level settings:

```python
results = [
    {"id": "doc1", "content": "...", "source": "doc",
     "score": 0.91, "rerank_score": 0.85,
     "rank": 1, "selected": True},
    {"id": "mem1", "content": "...", "source": "memory",
     "score": 0.52, "rerank_score": 0.30,
     "rank": 2, "selected": False},
    {"id": "blocked", "content": "...", "source": "memory",
     "score": 0.93, "rank": 3, "selected": False,
     "filtered": True,               # removed by metadata filters
     "reason": "Blocked by policy"}, # custom reason (fallback)
]
```

### Memory Chunk Diff

![Memory Chunk Diff](assets/diff-chunk.png)

The Diff tab now includes a first-class **side-by-side chunk comparison** that answers one question immediately: **"Which memory actually changed?"**

For every retrieved chunk, the chunk diff shows:

- **Chunk id** and **source/document**
- **Retrieval score** and **reranker score** (when available)
- **Selected / rejected** state in each run
- **Similarity delta** (Δ score between runs)

Each row is tagged with what changed:

| Tag | Meaning |
|---|---|
| `newly selected` | Chunk was selected for the final prompt only in the bad run |
| `deselected` | Chunk was selected in the good run but dropped in the bad run |
| `rank changed` | Same chunk moved rank (e.g. #7 → #1) — highlighted in both columns |
| `score changed` | Retrieval/reranker score moved — highlighted with the Δ |
| `newly retrieved` / `removed` | Chunk appeared / disappeared between runs |

When a different chunk replaced another in the final prompt, the UI explicitly calls it out:

> **Chunk `pricing_summary` replaced Chunk `july_pricing_update` in the final prompt.**

The chunk diff is rendered as a side-by-side table — good run on the left, bad run on the right — so a rank flip, a score drop, or a selection swap is visible at a glance.

---

## What You Get

| Tab | What it shows |
|---|---|
| **Replay** | The full run, step by step |
| **Prompt** | The exact final prompt the LLM saw |
| **Context** | Every context block, tagged by provenance |
| **Retrieval** | Candidates with scores, thresholds, filters, and a human-readable reason for every selection |
| **Memory** | The full memory lifecycle |
| **Tools** | Every call, args, and result |
| **Diff** | Good run vs bad run → likely cause, with a side-by-side memory chunk diff |

**Local-first.** Everything stays in an append-only SQLite log (`.agent_devtools/trace.db`). Nothing leaves your machine.

**Framework adapters.** LangChain and Groq work out of the box. More coming.

---

## Roadmap

- [x] Python SDK + local SQLite store
- [x] DevTools UI: Replay / Prompt / Context / Retrieval / Memory / Tools / Diff
- [x] LangChain + Groq adapters
- [x] CI debug assertions (`agent-devtools test fixtures/*.json`)
- [x] Memory Chunk Diff — side-by-side chunk comparison in the Diff tab
- [x] Retrieval Explanation — human-readable reasons for every selected/rejected candidate
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
│           ├── explain.py        # Retrieval Explanation engine
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