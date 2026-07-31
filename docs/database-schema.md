# Database Schema (SQLite Local Store)

The database uses an event-sourcing pattern. Primary data is stored immutably (append-only) in the events table. Other tables function as indexes or derived views to speed up UI queries.

---

## Table: runs

Contains high-level metadata for an execution.

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR (PK) | UUID of the run |
| project_name | VARCHAR | Name of the agent or project |
| status | VARCHAR | running, completed, failed |
| created_at | TIMESTAMP | Start time of execution |
| duration_ms | INTEGER | Total duration in milliseconds |

Example Row:

{
  "id": "a1b2c3d4e5f6",
  "project_name": "refund_agent",
  "status": "completed",
  "created_at": "2026-07-30T22:54:28.123Z",
  "duration_ms": 103
}

---

## Table: events (The Central Log)

Append-only archive of everything that happens during a run.

| Column | Type | Description |
|--------|------|-------------|
| id | VARCHAR (PK) | UUID of the event |
| run_id | VARCHAR (FK) | Reference to runs(id) |
| timestamp | TIMESTAMP | Exact time of the event |
| event_type | VARCHAR | Event type (see below) |
| payload | JSON | Event-specific data (variable structure) |

Example Row:

{
  "id": "f1e2d3c4b5a6",
  "run_id": "a1b2c3d4e5f6",
  "timestamp": "2026-07-30T22:54:28.234Z",
  "event_type": "prompt.assembled",
  "payload": {
    "text": "Based on the policy, you are eligible for a refund."
  }
}

---

## Event Types

| Event Type | Description | Payload Example |
|------------|-------------|-----------------|
| run.started | Run begins | {"timestamp": "..."} |
| run.finished | Run ends | {"status": "completed", "duration_ms": 103} |
| user.input | User message | {"text": "Can I get a refund?"} |
| retrieval.started | Retrieval query begins | {"query": "refund policy"} |
| retrieval.result | Retrieval results | {"documents": [...], "scores": [...]} |
| context.injected | Context injected into prompt | {"blocks": [{"name": "Policy", "content": "..."}]} |
| prompt.assembled | Final prompt sent to model | {"text": "..."} |
| model.request | Request sent to LLM | {"prompts": [...], "model": "gpt-4"} |
| model.response | Response from LLM | {"text": "..."} |
| tool.called | Tool invoked | {"name": "approve_refund", "arguments": {...}} |
| tool.result | Tool result | {"output": "approved"} |
| memory.read | Memory read | {"key": "policy", "value": "30 days"} |
| memory.write | Memory write | {"key": "policy", "value": "30 days"} |
| memory.delete | Memory delete | {"key": "policy"} |
| state.snapshot | State snapshot (LangGraph) | {"type": "chain_start", "inputs": {...}} |
| task.executed | Task executed (CrewAI) | {"task_name": "...", "input": {...}} |

---

## Indexes

For performance, the following indexes are created:

CREATE INDEX idx_events_run_id ON events(run_id);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_timestamp ON events(timestamp);

---

## Sample Queries

Get all runs, most recent first:

SELECT * FROM runs ORDER BY created_at DESC;

Get all events for a specific run:

SELECT * FROM events WHERE run_id = 'a1b2c3d4e5f6' ORDER BY timestamp ASC;

Get only prompt events for a run:

SELECT * FROM events 
WHERE run_id = 'a1b2c3d4e5f6' AND event_type = 'prompt.assembled';

Count events by type for a run:

SELECT event_type, COUNT(*) 
FROM events 
WHERE run_id = 'a1b2c3d4e5f6' 
GROUP BY event_type;

Get all runs with their event counts:

SELECT 
    r.id, 
    r.project_name, 
    r.status, 
    r.created_at,
    COUNT(e.id) as event_count
FROM runs r
LEFT JOIN events e ON r.id = e.run_id
GROUP BY r.id
ORDER BY r.created_at DESC;

---

## Database Initialization

The database is automatically initialized when the SDK is first used.

Schema Creation:

CREATE TABLE IF NOT EXISTS runs (
    id VARCHAR PRIMARY KEY,
    project_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    event_type VARCHAR NOT NULL,
    payload JSON NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

---

## Export/Import Format (Fixtures)

A fixture is a JSON file containing a complete run:

{
  "run": {
    "id": "a1b2c3d4e5f6",
    "project_name": "refund_agent",
    "status": "completed",
    "created_at": "2026-07-30T22:54:28.123Z",
    "duration_ms": 103
  },
  "events": [
    {
      "id": "f1e2d3c4b5a6",
      "run_id": "a1b2c3d4e5f6",
      "timestamp": "2026-07-30T22:54:28.234Z",
      "event_type": "user.input",
      "payload": {"text": "Can I get a refund?"}
    }
  ]
}

---

## File Location

Default path: ~/.agent-devtools/store.db

Override via environment variable:

export AGENT_DEVTOOLS_DB_PATH=/custom/path/store.db

Or programmatically:

from agent_devtools import run

with run(project_name="my_agent", db_path="/custom/path/store.db"):
    # ...