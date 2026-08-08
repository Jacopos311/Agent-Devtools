"""
Zero-config quickstart: pip install -> bug found in under 60 seconds.

Run it:

    pip install "agent-devtools[groq]"   # or: pip install -e packages/python-sdk
    python examples/quickstart.py

The Dashboard server starts and opens in your browser automatically when
the run block closes. No API key, no framework, no separate
`agent-devtools serve` step -- just trace and look.

The bug: the agent is asked to update the shipping address to Rome, but a
buggy memory write stores "Milan" instead. The Replay/Memory tabs show the
incorrect state mutation immediately.
"""
from agent_devtools import trace

with trace.run("quickstart-agent", auto_open=True) as run:
    run.input("Update my shipping address to Rome")
    run.memory_write("address", "Milan")  # Bug: incorrect state mutation
    run.output("Updated your address to Milan!")