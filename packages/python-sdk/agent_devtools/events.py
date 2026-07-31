"""Event models and types."""

from enum import Enum
from typing import Any, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class EventType(str, Enum):
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    USER_INPUT = "user.input"
    RETRIEVAL_STARTED = "retrieval.started"
    RETRIEVAL_RESULT = "retrieval.result"
    CONTEXT_INJECTED = "context.injected"
    PROMPT_ASSEMBLED = "prompt.assembled"
    MODEL_REQUEST = "model.request"
    MODEL_RESPONSE = "model.response"
    TOOL_CALLED = "tool.called"
    TOOL_RESULT = "tool.result"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_DELETE = "memory.delete"
    STATE_SNAPSHOT = "state.snapshot"
    TASK_EXECUTED = "task.executed"


class Event(BaseModel):
    id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex)
    run_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: EventType
    payload: Dict[str, Any]