"""FastAPI server for debugging."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import json

from .transport import Transport
from .schemas import (
    RunResponse, EventResponse, RunListResponse, EventListResponse,
    ImportResponse, DiffRequest, DiffResponse
)
from .services.diff_service import compare_runs

app = FastAPI(title="Agent DevTools Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _to_run_response(run: dict) -> RunResponse:
    return RunResponse(
        id=run["id"],
        project_name=run["project_name"],
        status=run["status"],
        created_at=run["created_at"],
        duration_ms=run.get("duration_ms")
    )


def _to_event_response(event: dict) -> EventResponse:
    return EventResponse(
        id=event["id"],
        run_id=event["run_id"],
        timestamp=event["timestamp"],
        event_type=event["event_type"],
        payload=json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/runs", response_model=RunListResponse)
async def list_runs(limit: int = 50, offset: int = 0):
    transport = Transport()
    runs = transport.list_runs(limit, offset)
    total = transport.count_runs()
    return RunListResponse(
        runs=[_to_run_response(r) for r in runs],
        total=total,
        limit=limit,
        offset=offset
    )


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str):
    transport = Transport()
    run = transport.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_run_response(run)


@app.get("/runs/{run_id}/events", response_model=EventListResponse)
async def get_events(run_id: str, event_type: Optional[str] = None, limit: int = 100, offset: int = 0):
    transport = Transport()
    run = transport.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    events = transport.get_events(run_id, event_type, limit, offset)
    total = transport.count_events(run_id, event_type)

    return EventListResponse(
        events=[_to_event_response(e) for e in events],
        total=total,
        limit=limit,
        offset=offset
    )


@app.get("/runs/{run_id}/export")
async def export_run(run_id: str):
    transport = Transport()
    try:
        data = transport.export_run(run_id)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/runs/import", response_model=ImportResponse)
async def import_run(data: dict):
    transport = Transport()
    try:
        run_id = transport.import_run(data)
        return ImportResponse(run_id=run_id, message="Import successful")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/runs/diff", response_model=DiffResponse)
async def diff_runs(request: DiffRequest):
    transport = Transport()
    try:
        result = compare_runs(request.run_a_id, request.run_b_id, transport)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))