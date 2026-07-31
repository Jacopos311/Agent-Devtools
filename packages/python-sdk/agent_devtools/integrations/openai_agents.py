"""Integration with OpenAI Agents SDK."""

from typing import Any, Dict, Optional
from .base import BaseTracer
from ..core import get_current_run_id
from ..events import EventType


class OpenAIAgentTracer(BaseTracer):
    """Tracer for OpenAI Agents SDK."""

    def __init__(self):
        super().__init__()

    def trace_input(self, input_text: str):
        self.emit(EventType.USER_INPUT, {"text": input_text})

    def trace_response(self, response):
        self.emit(EventType.MODEL_RESPONSE, {
            "text": response,
            "finish_reason": "stop"
        })

    def trace_tool_calls(self, tool_calls: list):
        for tool_call in tool_calls:
            self.emit(EventType.TOOL_CALLED, {
                "name": tool_call.get("name", "unknown"),
                "arguments": tool_call.get("arguments", {})
            })
            if "result" in tool_call:
                self.emit(EventType.TOOL_RESULT, {
                    "output": tool_call.get("result")
                })


def trace_openai_agent(agent, input_text: str, config: Optional[Dict] = None):
    """Run an OpenAI Agent with tracing."""
    run_id = get_current_run_id()
    if not run_id:
        raise RuntimeError("No active run context found")

    tracer = OpenAIAgentTracer()
    tracer.trace_input(input_text)

    try:
        # Import the agents SDK
        from agents import Runner

        if hasattr(Runner, "run"):
            result = Runner.run(agent, input_text, config=config or {})
        else:
            raise RuntimeError("OpenAI Agents SDK not properly installed")

        # Extract response
        response_text = str(result.final_output) if hasattr(result, "final_output") else str(result)
        tracer.trace_response(response_text)

        # Trace tool calls
        if hasattr(result, "tool_calls"):
            tracer.trace_tool_calls(result.tool_calls)

        return result

    except Exception as e:
        tracer.emit(EventType.RUN_FINISHED, {
            "status": "failed",
            "error": str(e)
        })
        raise