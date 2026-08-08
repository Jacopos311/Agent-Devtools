# Quickstart: pip install → bug found in under 60 seconds

The absolute fastest path from zero to a live, debuggable agent run.

```bash
pip install "agent-devtools[groq]"   # or: pip install -e packages/python-sdk
python examples/quickstart.py
```

That's it. The Dashboard server starts and opens in your browser
automatically when the run block closes — no API key, no framework, no
separate `agent-devtools serve` step.

## The whole example

```python
from agent_devtools import trace

with trace.run("quickstart-agent", auto_open=True) as run:
    run.input("Update my shipping address to Rome")
    run.memory_write("address", "Milan")  # Bug: incorrect state mutation
    run.output("Updated your address to Milan!")
```

Four executable lines. The agent is asked to update the shipping address
to **Rome**, but a buggy memory write stores **Milan** instead.

## Find the bug

Open the **Replay** tab: `user.input` → `memory.write` → `model.response`.
The **Memory** tab shows the incorrect state mutation (`address = "Milan"`)
that contradicts the user's request. That's the bug — visible in seconds,
no guessing.

## What makes this zero-config?

- `auto_open=True` starts the local debug server (background thread) and
  opens the Dashboard in your default browser as soon as the run closes.
- Everything stays local in `.agent_devtools/trace.db` — nothing leaves
  your machine.
- No `GROQ_API_KEY`, no LangChain, no LangGraph, no network calls.

## Explicit alternatives

Prefer to control when the server starts?

```python
from agent_devtools import trace

trace.serve()          # start the server (background) + open the browser
trace.open_ui()        # open the browser against an already-running server
```

Both are also available as `from agent_devtools import serve, open_ui`.