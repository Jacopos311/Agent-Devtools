# System Architecture

## Overview

Agent DevTools follows a local-first architecture based on 4 main layers. The data flow is unidirectional: the user's application emits immutable events (append-only) that are stored locally and served to a React UI for inspection.

┌─────────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                              │
│                  (Your AI Agent Code)                              │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│              1. INSTRUMENTATION SDK (Python)                       │
│                    agent-devtools                                  │
│                                                                     │
│  • Context manager: with devtools.run(...)                         │
│  • Event emission: emit(event_type, payload)                       │
│  • Redaction hooks for sensitive data                              │
│  • Framework integrations (LangGraph, OpenAI Agents, CrewAI)       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│              2. LOCAL TRACE STORE (SQLite)                         │
│                                                                     │
│  • Append-only event log                                           │
│  • Tables: runs, events                                            │
│  • No external dependencies                                        │
│  • Indexed for fast queries                                        │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│              3. DEBUG SERVER (FastAPI)                             │
│                                                                     │
│  • REST API endpoints                                              │
│  • /runs, /runs/{id}/events, /runs/diff                           │
│  • Export/import fixtures                                          │
│  • CORS enabled for local UI                                      │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│              4. DEVTOOLS UI (React / TypeScript)                   │
│                                                                     │
│  • Chrome DevTools-style interface                                 │
│  • Tab-based layout: Replay, Prompt, Context,                     │
│    Retrieval, Memory, Tools, Diff                                 │
│  • Fast navigation, dense information display                      │
└─────────────────────────────────────────────────────────────────────┘

---

## The 4 Layers in Detail

### 1. Instrumentation SDK (agent-devtools-python)

The core data acquisition layer. It captures execution spans locally without modifying the agent's logic.

Key Components:

| Component | Description |
|-----------|-------------|
| RunContext | Context manager that wraps a single agent execution. Handles run ID generation, timestamps, and status tracking. |
| Transport | Handles writing events to SQLite. Manages connection and schema initialization. |
| Redaction | Applies configurable hooks to remove sensitive data before storage. |
| Integrations | Framework-specific tracers for LangGraph, OpenAI Agents SDK, and CrewAI. |

Event Types:

- run.started / run.finished
- user.input
- retrieval.started / retrieval.result
- context.injected
- prompt.assembled
- model.request / model.response
- tool.called / tool.result
- memory.read / memory.write / memory.delete
- state.snapshot
- task.executed (CrewAI)

### 2. Local Trace Store (SQLite)

The local, persistent storage layer. It is:

- Zero-configuration – automatically initializes on first use
- Append-only – events are never modified, only added
- Indexed – optimized for chronological replay and filtering by event type
- Portable – the database file can be moved, shared, or backed up

Storage Location:

~/.agent-devtools/store.db

Override with the AGENT_DEVTOOLS_DB_PATH environment variable.

### 3. Debug Server (FastAPI)

A lightweight local server that exposes the data to the UI.

API Endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /health | Health check |
| GET | /runs | List runs with pagination |
| GET | /runs/{id} | Get run metadata |
| GET | /runs/{id}/events | Get events (with type filter, pagination) |
| GET | /runs/{id}/export | Export run as JSON fixture |
| POST | /runs/import | Import a fixture |
| POST | /runs/diff | Compare two runs |

CORS: Enabled for local development (allow_origins=["*"]).

### 4. DevTools UI (React / TypeScript)

The user interface, designed to be fast and information-dense, similar to Chrome DevTools.

Tabs:

| Tab | Purpose |
|-----|---------|
| Replay | Chronological event timeline. Click any event to inspect its payload. |
| Prompt | Shows the assembled prompt sent to the model. |
| Context | Displays injected context blocks and state snapshots. |
| Retrieval | Shows queries, retrieved documents, and relevance scores. |
| Memory | Displays memory read/write/delete operations. |
| Tools | Shows tool calls and their results. |
| Diff | Side-by-side comparison of two runs. |

---

## Data Pipeline

Agent Code
    │
    ▼
SDK (event emission)
    │
    ▼
SQLite (append-only log)
    │
    ▼
Derived Views (SQL queries)
    │
    ▼
FastAPI (REST endpoints)
    │
    ▼
React UI (visualization)

---

## Repository Structure

agent-devtools/
├── apps/
│   └── web/                     # React UI (Vite + TypeScript)
├── packages/
│   └── python-sdk/              # Python SDK + FastAPI server
│       ├── agent_devtools/      # Core package
│       │   ├── core.py          # RunContext, context manager
│       │   ├── events.py        # Event models and types
│       │   ├── transport.py     # SQLite layer
│       │   ├── redaction.py     # Sensitive data redaction
│       │   ├── cli.py           # Command-line interface
│       │   ├── server.py        # FastAPI server
│       │   ├── schemas.py       # Pydantic API models
│       │   ├── assertions.py    # Testing assertion engine
│       │   ├── test_runner.py   # Test execution
│       │   ├── services/        # Business logic
│       │   │   └── diff_service.py
│       │   └── integrations/    # Framework integrations
│       │       ├── langgraph.py
│       │       ├── openai_agents.py
│       │       └── crewai.py
│       └── tests/               # Unit and integration tests
├── examples/                    # Example agents and demos
│   ├── simple_agent/            # Basic usage
│   ├── refund_agent/            # Stale memory bug demo
│   └── integrations/            # Framework examples
├── schemas/                     # JSON Schema definitions
└── docs/                        # Documentation

---

## Security Considerations

- Local-first: No data leaves your machine.
- Redaction: Sensitive keys are redacted by default (api_key, token, password, secret, authorization).
- Extensible: Custom redactors can be added to the context manager.
- No telemetry: The tool does not send any usage data.

---

## Performance

- SDK overhead: Minimal – each event is a small JSON write to SQLite.
- Server: FastAPI is lightweight and handles local requests efficiently.
- UI: Optimized with React and Vite for fast rendering.

---

## Extensibility

Agent DevTools is designed to be extended:

1. New Event Types: Add new types to EventType enum.
2. New Framework Integrations: Extend BaseTracer and implement the tracer.
3. Custom UI Components: The React codebase is modular.
4. Custom Assertions: Add new assertion types to the testing engine.
