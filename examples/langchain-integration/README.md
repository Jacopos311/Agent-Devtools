# LangChain integration example

This example shows how to bridge a LangChain chain into agent-devtools
using the `LangChainTraceHandler` callback handler.

## What it does

The example builds a small LangChain chain that:

1. Retrieves documents from an in-memory retriever
2. Assembles a prompt from the retrieved context
3. Calls a fake chat model (no API key needed)
4. Invokes a tool

Every LangChain callback event is recorded into the agent-devtools
SQLite store (`.agent_devtools/trace.db` by default).

## Run it

```bash
cd examples/langchain-integration
python run_example.py
```

This creates two runs:

- `langchain-example-1` — attached to an existing `trace.run(...)` block
- `langchain-example-2` — created and finished by the handler itself

## Verify the traces

Check the SQLite store directly:

```bash
python verify_traces.py
```

You should see both runs with events for `user.input`, `retrieval.query`,
`retrieval.result`, `prompt.assembled`, `model.response`, `tool.call`,
and `tool.result`.

## Inspect the traces

```bash
agent-devtools serve
```

Open http://127.0.0.1:4173 and look at the **Replay**, **Prompt**,
**Retrieval**, and **Tools** tabs for the `langchain-agent` runs.

## Event mapping

| LangChain callback | agent-devtools event |
|---|---|
| `on_chain_start` (root) | `user.input` |
| `on_chain_end` (root) | `model.response` |
| `on_llm_start` / `on_chat_model_start` | `prompt.assembled` |
| `on_llm_end` | `model.response` |
| `on_tool_start` | `tool.call` |
| `on_tool_end` | `tool.result` |
| `on_retriever_start` | `retrieval.query` |
| `on_retriever_end` | `retrieval.result` |