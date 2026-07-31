"""Integration with LangGraph."""

import asyncio
from typing import Any, Dict, Optional
from .base import BaseTracer
from ..core import get_current_run_id
from ..events import EventType


class LangGraphTracer(BaseTracer):
    """LangChain/LangGraph callback handler for tracing."""

    def __init__(self):
        super().__init__()

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.emit(EventType.STATE_SNAPSHOT, {
            "type": "chain_start",
            "inputs": inputs
        })

    def on_chain_end(self, outputs, **kwargs):
        self.emit(EventType.STATE_SNAPSHOT, {
            "type": "chain_end",
            "outputs": outputs
        })

    def on_llm_start(self, serialized, prompts, **kwargs):
        self.emit(EventType.MODEL_REQUEST, {
            "prompts": prompts,
            "model": serialized.get("name") if serialized else None
        })

    def on_llm_end(self, response, **kwargs):
        self.emit(EventType.MODEL_RESPONSE, {
            "response": response
        })

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.emit(EventType.TOOL_CALLED, {
            "name": serialized.get("name") if serialized else "unknown",
            "input": input_str
        })

    def on_tool_end(self, output, **kwargs):
        self.emit(EventType.TOOL_RESULT, {
            "output": output
        })


def trace_langgraph(graph, initial_state: Dict[str, Any], config: Optional[Dict] = None):
    """Run a LangGraph with tracing."""
    run_id = get_current_run_id()
    if not run_id:
        raise RuntimeError("No active run context found")

    tracer = LangGraphTracer()

    try:
        # Execute the graph
        if hasattr(graph, "ainvoke"):
            result = asyncio.run(graph.ainvoke(initial_state, config=config or {}))
        else:
            result = graph.invoke(initial_state, config=config or {})

        # Record prompt assembled if available
        prompt = result.get("messages", []) if isinstance(result, dict) else []
        if prompt:
            tracer.emit(EventType.PROMPT_ASSEMBLED, {
                "text": str(prompt[-1].content) if prompt and hasattr(prompt[-1], "content") else str(prompt)
            })

        return result

    except Exception as e:
        tracer.emit(EventType.RUN_FINISHED, {
            "status": "failed",
            "error": str(e)
        })
        raise