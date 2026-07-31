"""Pydantic schemas for API."""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class RunResponse(BaseModel):
    id: str
    project_name: str
    status: str
    created_at: str
    duration_ms: Optional[int] = None


class EventResponse(BaseModel):
    id: str
    run_id: str
    timestamp: str
    event_type: str
    payload: Dict[str, Any]


class RunListResponse(BaseModel):
    runs: List[RunResponse]
    total: int
    limit: int
    offset: int


class EventListResponse(BaseModel):
    events: List[EventResponse]
    total: int
    limit: int
    offset: int


class ImportResponse(BaseModel):
    run_id: str
    message: str


class DiffRequest(BaseModel):
    run_a_id: str
    run_b_id: str


class DiffItem(BaseModel):
    path: str
    type: str  # "added", "removed", "changed"
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None


class DiffResponse(BaseModel):
    run_a_id: str
    run_b_id: str
    differences_by_category: Dict[str, List[DiffItem]]
    total_differences: int