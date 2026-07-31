"""Integration with CrewAI."""

from typing import Any, Dict, Optional
from .base import BaseTracer
from ..core import get_current_run_id
from ..events import EventType


class CrewAITracer(BaseTracer):
    """Tracer for CrewAI."""

    def __init__(self):
        super().__init__()

    def trace_task(self, task_name: str, input_data: Dict, output_data: Optional[Dict] = None):
        self.emit(EventType.TASK_EXECUTED, {
            "task_name": task_name,
            "input": input_data,
            "output": output_data
        })


def trace_crew(crew, inputs: Optional[Dict] = None):
    """Run a CrewAI crew with tracing."""
    run_id = get_current_run_id()
    if not run_id:
        raise RuntimeError("No active run context found")

    tracer = CrewAITracer()

    try:
        # Import CrewAI
        from crewai import Crew

        # Execute the crew
        result = crew.kickoff(inputs=inputs or {})

        # Extract task results
        if hasattr(result, "tasks"):
            for task in result.tasks:
                tracer.trace_task(
                    task_name=task.name,
                    input_data=task.input,
                    output_data=task.output
                )

        return result

    except Exception as e:
        tracer.emit(EventType.RUN_FINISHED, {
            "status": "failed",
            "error": str(e)
        })
        raise