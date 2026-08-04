"""
agent_devtools
===============

A local-first causal debugger for AI agent runs.

    from agent_devtools import trace

    with trace.run("refund-agent") as run:
        run.input(user_message)
        run.retrieval(query, results)
        run.context_block(source="memory", key="pricing", content="...")
        run.prompt(system=system_prompt, messages=messages)
        run.tool_call(name="lookup_order", args={...}, result={...})
        run.memory_write(key="last_price", value="19.99")
        run.output(response_text)

Then, from a terminal in the same project:

    agent-devtools serve

and open the local DevTools UI to see exactly what the agent saw, in what
order, and why it answered the way it did.
"""

from . import trace  # noqa: F401
from . import explain  # noqa: F401
from .store import TraceStore, default_db_path  # noqa: F401
from .diff import diff_runs  # noqa: F401
from .adapters import LangChainTraceHandler  # noqa: F401
from .adapters.groq import TracedGroq, create_groq_llm, wrap_groq  # noqa: F401
from .debugger import AgentDebugger  # noqa: F401
from .debugger import DEFAULT_UI_PORT  # noqa: F401

__all__ = [
    "trace",
    "explain",
    "TraceStore",
    "default_db_path",
    "diff_runs",
    "LangChainTraceHandler",
    "TracedGroq",
    "create_groq_llm",
    "wrap_groq",
    "AgentDebugger",
    "DEFAULT_UI_PORT",
]
__version__ = "0.2.0"
