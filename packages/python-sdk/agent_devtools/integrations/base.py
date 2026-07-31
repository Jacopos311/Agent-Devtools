"""Base classes for tracers."""

from typing import Dict, Any
from ..core import get_current_run_id
from ..transport import Transport
from ..events import EventType, Event


class BaseTracer:
    """Base tracer that emits events to the current run."""

    def __init__(self):
        self.run_id = get_current_run_id()
        if not self.run_id:
            raise RuntimeError("No active run context found")

    def emit(self, event_type: EventType, payload: Dict[str, Any]):
        """Emit an event to the current run."""
        transport = Transport()
        event = Event(
            run_id=self.run_id,
            event_type=event_type,
            payload=payload
        )
        transport.write_event(event)