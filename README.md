# AGENT_DEVTOOLS_DOCS.md

## Indice
1. README.md
2. docs/architecture.md
3. docs/database-schema.md
4. docs/integration-guide.md
5. docs/user-guide.md

---

## 1. README.md
[contenuto completo]

---

## 2. docs/architecture.md
[contenuto completo]

... e così via
Questo risolve il problema: l'utente copia un singolo file, lo salva come AGENT_DEVTOOLS_DOCS.md, e ha tutta la documentazione in un unico posto. Poi può estrarre le singole sezioni se necessario.

Devo essere veloce e preciso, senza ulteriori scuse o spiegazioni. L'utente vuole il file, punto.

Hai ragione, scusa. Ecco TUTTO in un UNICO file markdown da copiare con un click.

markdown
# AGENT_DEVTOOLS_DOCS.md

## Indice

1. [README.md](#readmemd)
2. [docs/architecture.md](#docsarchitecturemd)
3. [docs/database-schema.md](#docsdatabase-schemamd)
4. [docs/integration-guide.md](#docsintegration-guidemd)
5. [docs/user-guide.md](#docsuser-guidemd)

---

## README.md

# Agent DevTools

**Local-first debugger for AI agents.**

Answer the question: *"Why did my agent behave this way?"*

Agent DevTools is the equivalent of Chrome DevTools for AI agent engineering. It provides complete visibility into your agent's decision-making process: user input, retrieved memory, prompt assembly, injected context, tool usage, and model responses.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage Examples](#usage-examples)
  - [Basic Usage](#basic-usage)
  - [OpenAI Agents SDK](#openai-agents-sdk)
  - [LangGraph / LangChain](#langgraph-langchain)
  - [CrewAI](#crewai)
- [UI Overview](#ui-overview)
- [Behavior Diff](#behavior-diff)
- [Testing & Assertions](#testing-assertions)
- [Configuration](#configuration)
- [Integration Guide](#integration-guide)
- [Development](#development)
- [License](#license)

---

## Overview

Agent DevTools is a **local-first**, **causal debugger** for AI agents. Unlike cloud-based monitoring platforms, it runs entirely on your machine, giving you full control over your data and debugging workflow.

**Core Promise:** Given a run of an agent, a developer must be able to immediately answer:

- What context did the model actually see?
- Which specific documents or memories influenced the response?
- What changed from the last successful execution? (Behavior Diff)
- Is the failure due to retrieval, prompt assembly, or model hallucination?

---

## Features

| Feature | Description |
|---------|-------------|
| **Python SDK** | Lightweight, non-intrusive instrumentation for any Python agent |
| **Local Trace Store** | SQLite-based append-only event log with zero configuration |
| **DevTools UI** | Chrome DevTools-style interface with dedicated tabs for Replay, Prompt, Context, Retrieval, Memory, Tools, and Diff |
| **Behavior Diff** | Compare any two runs to identify differences in prompts, context, memory, and tool outputs |
| **Export/Import** | Save runs as JSON fixtures for bug reports or regression tests |
| **Testing Framework** | Assertion-based testing with CLI support for CI/CD |
| **Framework Integrations** | OpenAI Agents SDK, LangGraph / LangChain, CrewAI |

---

## Architecture
┌─────────────────────────────────────────────────────────────┐
│ APPLICATION LAYER │
│ (Your AI Agent Code) │
└─────────────────────────┬───────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ 1. INSTRUMENTATION SDK (Python) │
│ agent-devtools │
│ │
│ - Context manager: with devtools.run(...) │
│ - Event emission: emit(event_type, payload) │
│ - Redaction hooks for sensitive data │
│ - Framework integrations │
└─────────────────────────┬───────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ 2. LOCAL TRACE STORE (SQLite) │
│ │
│ - Append-only event log │
│ - Tables: runs, events │
│ - No external dependencies │
│ - Indexed for fast queries │
└─────────────────────────┬───────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ 3. DEBUG SERVER (FastAPI) │
│ │
│ - REST API endpoints │
│ - Export/import fixtures │
│ - CORS enabled for local UI │
└─────────────────────────┬───────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────┐
│ 4. DEVTOOLS UI (React / TypeScript) │
│ │
│ - Chrome DevTools-style interface │
│ - Tab-based layout │
│ - Fast navigation │
└─────────────────────────────────────────────────────────────┘

text

### Data Flow
Agent Code → Python SDK → Event Stream → SQLite → Derived Views → REST API → DevTools UI

text

---

## Installation

### Prerequisites

- Python 3.10 or higher
- Node.js 18 or higher
- Poetry (recommended) or pip
- pnpm (recommended) or npm

### Clone and Install

```bash
git clone https://github.com/your-username/agent-devtools.git
cd agent-devtools
Install Python SDK
bash
cd packages/python-sdk
poetry install
Or with pip:

bash
pip install -e .
Install UI
bash
cd apps/web
pnpm install
Or with npm:

bash
npm install
Quick Start
Step 1: Start the Debug Server
bash
cd packages/python-sdk
poetry run agent-devtools serve
The server will be available at http://localhost:8787

Step 2: Start the UI
bash
cd apps/web
pnpm dev
The UI will be available at http://localhost:5173

Step 3: Run Your First Agent
Create a file my_agent.py:

from agent_devtools import run, EventType

def emit(event_type, payload):
    from agent_devtools import get_current_run_id
    from agent_devtools.transport import Transport
    from agent_devtools.events import Event
    run_id = get_current_run_id()
    if run_id:
        event = Event(run_id=run_id, event_type=event_type, payload=payload)
        Transport().write_event(event)

def my_agent():
    with run(project_name="My First Agent"):
        emit("user.input", {"text": "Hello, agent!"})
        emit("prompt.assembled", {"text": "You said: Hello, agent!"})
        emit("model.response", {"text": "Hello, user!"})
        print("Agent finished successfully!")

if __name__ == "__main__":
    my_agent()
Step 4: Run the Agent
bash
python my_agent.py
Step 5: Inspect in UI
Open http://localhost:5173 to see your run in the DevTools interface.

Usage Examples
Basic Usage
from agent_devtools import run, EventType

def emit(event_type, payload):
    from agent_devtools import get_current_run_id
    from agent_devtools.transport import Transport
    from agent_devtools.events import Event
    run_id = get_current_run_id()
    if run_id:
        event = Event(run_id=run_id, event_type=event_type, payload=payload)
        Transport().write_event(event)

with run(project_name="Refund Agent"):
    # Log user input
    emit("user.input", {"text": "Can I get a refund?"})
    
    # Log retrieval
    emit("retrieval.started", {"query": "refund policy"})
    emit("retrieval.result", {
        "documents": [{"id": "policy_2026", "content": "30 days refund policy"}],
        "scores": [0.98]
    })
    
    # Log context injection
    emit("context.injected", {
        "blocks": [
            {"name": "Policy", "content": "30 days refund policy"},
            {"name": "User", "content": "Order #12345"}
        ]
    })
    
    # Log prompt assembly
    emit("prompt.assembled", {
        "text": "Based on the policy, the user is eligible for a refund."
    })
    
    # Log model response
    emit("model.response", {
        "text": "You are eligible for a refund within 30 days."
    })
    
    # Log tool calls
    emit("tool.called", {"name": "approve_refund", "arguments": {"order": "12345"}})
    emit("tool.result", {"output": "approved"})
OpenAI Agents SDK
from agents import Agent, Runner
from agent_devtools import run
from agent_devtools.integrations.openai_agents import trace_openai_agent

agent = Agent(
    name="Refund Assistant",
    instructions="Help users with refund requests."
)

with run(project_name="OpenAI Agent"):
    result = trace_openai_agent(
        agent,
        "Can I get a refund for order #12345?"
    )
LangGraph / LangChain
from langgraph.graph import StateGraph, END
from agent_devtools import run
from agent_devtools.integrations.langgraph import trace_langgraph

def agent_node(state):
    return {"messages": state["messages"] + ["Agent processing..."]}

graph = StateGraph(State)
graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
graph.set_finish_point("agent")
compiled = graph.compile()

with run(project_name="LangGraph Agent"):
    result = trace_langgraph(compiled, {"messages": []})
CrewAI
from crewai import Agent, Task, Crew
from agent_devtools import run
from agent_devtools.integrations.crewai import trace_crew

refund_agent = Agent(
    role="Refund Specialist",
    goal="Process refund requests accurately"
)

refund_task = Task(
    description="Process refund for order #12345",
    agent=refund_agent
)

crew = Crew(agents=[refund_agent], tasks=[refund_task])

with run(project_name="CrewAI Demo"):
    result = trace_crew(crew, inputs={"order": "12345"})
UI Overview
Run List
The landing page displays all runs with project name, status, creation date, and duration. Click "Inspect" to open a specific run.

Tabs
Tab	Description
Replay	Chronological timeline of all events. Click any event to see its payload.
Prompt	Displays the assembled prompt that was sent to the model.
Context	Shows injected context blocks and state snapshots.
Retrieval	Displays retrieval queries, results, and relevance scores.
Memory	Shows memory read, write, and delete operations.
Tools	Displays tool calls and their results.
Diff	Compare two runs side-by-side with visual highlighting.
Behavior Diff
The Diff feature is the killer functionality of Agent DevTools. It allows you to compare any two runs to identify what changed between them.

Usage
Open any run in the UI

Navigate to the Diff tab

Select Run A (baseline) and Run B (comparison)

Click "Compare"

What Gets Compared
Category	Description
Prompt	Differences in assembled prompts
Context	Added/removed/changed context blocks
Retrieval	Different queries, results, or scores
Memory	Different memory values read or written
Tools	Different tool calls or arguments
Example Use Case
The examples/refund_agent/ demonstrates a classic bug: the agent uses stale memory (14-day policy) instead of the current policy (30-day policy). The Diff tab immediately shows the discrepancy in the prompt.

Testing & Assertions
Agent DevTools includes a testing framework for regression testing of agent behavior.

Creating a Test
Create a JSON test file:

json
{
  "name": "Refund Policy Test",
  "fixture_path": "fixtures/correct_run.json",
  "assertions": [
    {
      "type": "tool_called",
      "tool_name": "approve_refund"
    },
    {
      "type": "context_block_present",
      "block_name": "Policy",
      "contains": "30 days"
    },
    {
      "type": "prompt_contains",
      "text": "refund"
    },
    {
      "type": "event_absent",
      "event_type": "tool.called",
      "payload_match": {"name": "reject_refund"}
    }
  ]
}
Available Assertions
Assertion Type	Description	Required Parameters
event_present	Event exists	event_type, payload_match (optional)
event_absent	Event does not exist	event_type, payload_match (optional)
context_block_present	Context block exists	block_name, contains (optional)
prompt_contains	Prompt contains text	text
tool_called	Tool was called	tool_name
tool_not_called	Tool was not called	tool_name
Running Tests
bash
agent-devtools test tests/ --verbose
CI/CD Integration
bash
agent-devtools test tests/ --json > test_results.json
Exit code is 0 if all tests pass, 1 if any fail.

Configuration
Database Location
By default, the database is stored at ~/.agent-devtools/store.db. To override:

bash
export AGENT_DEVTOOLS_DB_PATH=/path/to/custom/store.db
Server Port
bash
agent-devtools serve --port 8788
Redaction
Sensitive keys are automatically redacted. Default redacted keys:

text
api_key, token, password, secret, authorization
Custom redactors can be passed to the run() context manager:

python
def custom_redactor(payload):
    if "email" in payload:
        payload["email"] = "***REDACTED***"
    return payload

with run(project_name="My Agent", redactors=[custom_redactor]):
    # ...
Integration Guide
Manual Instrumentation
For any Python agent (including direct API calls to ChatGPT, Gemini, Claude, etc.):

python
from agent_devtools import run, EventType

def emit(event_type, payload):
    from agent_devtools import get_current_run_id
    from agent_devtools.transport import Transport
    from agent_devtools.events import Event
    run_id = get_current_run_id()
    if run_id:
        event = Event(run_id=run_id, event_type=event_type, payload=payload)
        Transport().write_event(event)

def my_agent(input_text):
    with run(project_name="My Agent"):
        # Log user input
        emit("user.input", {"text": input_text})
        
        # Log retrieval
        emit("retrieval.started", {"query": "search query"})
        emit("retrieval.result", {"documents": [...]})
        
        # Log model request (any model)
        emit("model.request", {"model": "gemini-1.5-pro", "prompt": "..."})
        response = call_gemini_api(...)
        emit("model.response", {"text": response})
        
        # Log tool calls
        emit("tool.called", {"name": "tool_name", "arguments": {...}})
        emit("tool.result", {"output": "..."})
        
        return response
Framework Integrations
Framework	Installation	Import
OpenAI Agents SDK	pip install agent-devtools[openai-agents]	from agent_devtools.integrations.openai_agents import trace_openai_agent
LangGraph / LangChain	pip install agent-devtools[langgraph]	from agent_devtools.integrations.langgraph import trace_langgraph
CrewAI	pip install agent-devtools[crewai]	from agent_devtools.integrations.crewai import trace_crew
For detailed integration instructions, see the Integration Guide.

Development
Project Structure
text
agent-devtools/
├── apps/
│   └── web/             # React UI (Vite + TypeScript)
├── packages/
│   └── python-sdk/      # Python SDK + FastAPI server
│       ├── agent_devtools/   # Core package
│       ├── tests/            # Unit and integration tests
│       └── pyproject.toml    # Poetry configuration
├── examples/            # Example agents and demos
│   ├── simple_agent/    # Minimal example
│   ├── refund_agent/    # Demo with stale memory bug
│   └── integrations/    # Framework integration examples
├── schemas/             # JSON Schema definitions
└── docs/                # Documentation
Running Tests
bash
cd packages/python-sdk
poetry run pytest
Code Style
bash
cd packages/python-sdk
poetry run ruff .
poetry run mypy .
License
MIT License. See LICENSE for details.

Contributing
Contributions are welcome! Please see CONTRIBUTING.md for guidelines.

Fork the repository

Create a feature branch

Make your changes

Run tests

Submit a pull request

Support
Issues: GitHub Issues

Documentation: docs/

Examples: examples/

Agent DevTools - Because understanding your agent shouldn't be a black box.

docs/architecture.md
System Architecture
Overview
Agent DevTools follows a local-first architecture based on 4 main layers.

text
┌─────────────────────────────────────────────────────────────┐
│                   APPLICATION LAYER                        │
│                (Your AI Agent Code)                        │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│          1. INSTRUMENTATION SDK (Python)                   │
│                    agent-devtools                          │
│                                                             │
│  - Context manager: with devtools.run(...)                 │
│  - Event emission: emit(event_type, payload)               │
│  - Redaction hooks for sensitive data                      │
│  - Framework integrations                                  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│          2. LOCAL TRACE STORE (SQLite)                     │
│                                                             │
│  - Append-only event log                                   │
│  - Tables: runs, events                                    │
│  - No external dependencies                                │
│  - Indexed for fast queries                                │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│          3. DEBUG SERVER (FastAPI)                         │
│                                                             │
│  - REST API endpoints                                      │
│  - Export/import fixtures                                  │
│  - CORS enabled for local UI                               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│          4. DEVTOOLS UI (React / TypeScript)               │
│                                                             │
│  - Chrome DevTools-style interface                         │
│  - Tab-based layout                                        │
│  - Fast navigation                                         │
└─────────────────────────────────────────────────────────────┘
The 4 Layers in Detail
Layer 1: Instrumentation SDK (agent-devtools-python)
The core data acquisition layer. Captures execution spans locally.

Key Components:

Component	Description
RunContext	Context manager that wraps a single agent execution. Handles run ID generation, timestamps, and status tracking.
Transport	Handles writing events to SQLite. Manages connection and schema initialization.
Redaction	Applies configurable hooks to remove sensitive data before storage.
Integrations	Framework-specific tracers for LangGraph, OpenAI Agents SDK, and CrewAI.
Event Types:

run.started / run.finished

user.input

retrieval.started / retrieval.result

context.injected

prompt.assembled

model.request / model.response

tool.called / tool.result

memory.read / memory.write / memory.delete

state.snapshot

task.executed (CrewAI)

Layer 2: Local Trace Store (SQLite)
The local, persistent storage layer.

Characteristics:

Zero-configuration – automatically initializes on first use

Append-only – events are never modified, only added

Indexed – optimized for chronological replay and filtering

Portable – the database file can be moved, shared, or backed up

Storage Location:

~/.agent-devtools/store.db

Override with the AGENT_DEVTOOLS_DB_PATH environment variable.

Layer 3: Debug Server (FastAPI)
A lightweight local server that exposes the data to the UI.

API Endpoints:

Method	Endpoint	Description
GET	/health	Health check
GET	/runs	List runs with pagination
GET	/runs/{id}	Get run metadata
GET	/runs/{id}/events	Get events (with type filter, pagination)
GET	/runs/{id}/export	Export run as JSON fixture
POST	/runs/import	Import a fixture
POST	/runs/diff	Compare two runs
CORS: Enabled for local development (allow_origins=["*"]).

Layer 4: DevTools UI (React / TypeScript)
The user interface, designed to be fast and information-dense.

Tabs:

Tab	Purpose
Replay	Chronological event timeline. Click any event to inspect its payload.
Prompt	Shows the assembled prompt sent to the model.
Context	Displays injected context blocks and state snapshots.
Retrieval	Shows queries, retrieved documents, and relevance scores.
Memory	Displays memory read/write/delete operations.
Tools	Shows tool calls and their results.
Diff	Side-by-side comparison of two runs.
Data Pipeline
text
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
Repository Structure
text
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
Security Considerations
Local-first: No data leaves your machine.

Redaction: Sensitive keys are redacted by default (api_key, token, password, secret, authorization).

Extensible: Custom redactors can be added to the context manager.

No telemetry: The tool does not send any usage data.

Performance
SDK overhead: Minimal – each event is a small JSON write to SQLite.

Server: FastAPI is lightweight and handles local requests efficiently.

UI: Optimized with React and Vite for fast rendering.

Extensibility
Agent DevTools is designed to be extended:

New Event Types: Add new types to EventType enum.

New Framework Integrations: Extend BaseTracer and implement the tracer.

Custom UI Components: The React codebase is modular.

Custom Assertions: Add new assertion types to the testing engine.

docs/database-schema.md
Database Schema (SQLite Local Store)
The database uses an event-sourcing pattern. Primary data is stored immutably (append-only) in the events table. Other tables function as indexes or derived views to speed up UI queries.

Table: runs
Contains high-level metadata for an execution.

Columns:

Column	Type	Description
id	VARCHAR (PK)	UUID of the run
project_name	VARCHAR	Name of the agent or project
status	VARCHAR	running, completed, failed
created_at	TIMESTAMP	Start time of execution
duration_ms	INTEGER	Total duration in milliseconds
Example Row:

json
{
  "id": "a1b2c3d4e5f6",
  "project_name": "refund_agent",
  "status": "completed",
  "created_at": "2026-07-30T22:54:28.123Z",
  "duration_ms": 103
}
Table: events (The Central Log)
Append-only archive of everything that happens during a run.

Columns:

Column	Type	Description
id	VARCHAR (PK)	UUID of the event
run_id	VARCHAR (FK)	Reference to runs(id)
timestamp	TIMESTAMP	Exact time of the event
event_type	VARCHAR	Event type (see below)
payload	JSON	Event-specific data (variable structure)
Example Row:

json
{
  "id": "f1e2d3c4b5a6",
  "run_id": "a1b2c3d4e5f6",
  "timestamp": "2026-07-30T22:54:28.234Z",
  "event_type": "prompt.assembled",
  "payload": {
    "text": "Based on the policy, you are eligible for a refund."
  }
}
Event Types
Event Type	Description	Payload Example
run.started	Run begins	{"timestamp": "..."}
run.finished	Run ends	{"status": "completed", "duration_ms": 103}
user.input	User message	{"text": "Can I get a refund?"}
retrieval.started	Retrieval query begins	{"query": "refund policy"}
retrieval.result	Retrieval results	{"documents": [...], "scores": [...]}
context.injected	Context injected into prompt	{"blocks": [{"name": "Policy", "content": "..."}]}
prompt.assembled	Final prompt sent to model	{"text": "..."}
model.request	Request sent to LLM	{"prompts": [...], "model": "gpt-4"}
model.response	Response from LLM	{"text": "..."}
tool.called	Tool invoked	{"name": "approve_refund", "arguments": {...}}
tool.result	Tool result	{"output": "approved"}
memory.read	Memory read	{"key": "policy", "value": "30 days"}
memory.write	Memory write	{"key": "policy", "value": "30 days"}
memory.delete	Memory delete	{"key": "policy"}
state.snapshot	State snapshot (LangGraph)	{"type": "chain_start", "inputs": {...}}
task.executed	Task executed (CrewAI)	{"task_name": "...", "input": {...}}
Indexes
For performance, the following indexes are created:

sql
CREATE INDEX idx_events_run_id ON events(run_id);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_timestamp ON events(timestamp);
Sample Queries
Get all runs, most recent first:

sql
SELECT * FROM runs ORDER BY created_at DESC;
Get all events for a specific run:

sql
SELECT * FROM events WHERE run_id = 'a1b2c3d4e5f6' ORDER BY timestamp ASC;
Get only prompt events for a run:

sql
SELECT * FROM events 
WHERE run_id = 'a1b2c3d4e5f6' AND event_type = 'prompt.assembled';
Count events by type for a run:

sql
SELECT event_type, COUNT(*) 
FROM events 
WHERE run_id = 'a1b2c3d4e5f6' 
GROUP BY event_type;
Get all runs with their event counts:

sql
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
Database Initialization
The database is automatically initialized when the SDK is first used.

Schema Creation:

sql
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
Export/Import Format (Fixtures)
A fixture is a JSON file containing a complete run:

json
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
File Location
Default path: ~/.agent-devtools/store.db

Override via environment variable:

bash
export AGENT_DEVTOOLS_DB_PATH=/custom/path/store.db
Override programmatically:

python
from agent_devtools import run

with run(project_name="my_agent", db_path="/custom/path/store.db"):
    # ...
Relationships
text
┌─────────────┐          ┌─────────────┐
│    runs     │          │   events    │
├─────────────┤          ├─────────────┤
│ id (PK)     │◄─────────│ run_id (FK) │
│ project_name│          │ id (PK)     │
│ status      │          │ timestamp   │
│ created_at  │          │ event_type  │
│ duration_ms │          │ payload     │
└─────────────┘          └─────────────┘
     1                          N
A run has many events. Each event belongs to exactly one run.

docs/integration-guide.md
Integration Guide
This guide explains how to integrate Agent DevTools with your AI agent framework.

Overview
Agent DevTools provides two ways to instrument your agent:

Manual Instrumentation – Use the run() context manager and emit() function directly. Works with any Python code, including direct API calls to ChatGPT, Gemini, Claude, etc.

Framework Integrations – Use built-in tracers for popular frameworks (OpenAI Agents SDK, LangGraph, CrewAI). These automatically capture events.

Manual Instrumentation
Basic Setup
python
from agent_devtools import run, EventType

def my_agent(input_text):
    with run(project_name="My Agent"):
        # Your agent logic here
        result = ...
        return result
Emitting Events
Inside the context manager, use the emit() function to log events:

python
from agent_devtools import run, EventType

def emit(event_type, payload):
    from agent_devtools import get_current_run_id
    from agent_devtools.transport import Transport
    from agent_devtools.events import Event
    
    run_id = get_current_run_id()
    if run_id:
        event = Event(run_id=run_id, event_type=event_type, payload=payload)
        Transport().write_event(event)

with run(project_name="My Agent"):
    # Log user input
    emit("user.input", {"text": "Hello, agent!"})
    
    # Log a prompt
    emit("prompt.assembled", {"text": "You said: Hello, agent!"})
    
    # Log a model response
    emit("model.response", {"text": "Hello, user!"})
Complete Example
python
from agent_devtools import run, EventType

def emit(event_type, payload):
    from agent_devtools import get_current_run_id
    from agent_devtools.transport import Transport
    from agent_devtools.events import Event
    run_id = get_current_run_id()
    if run_id:
        event = Event(run_id=run_id, event_type=event_type, payload=payload)
        Transport().write_event(event)

def my_agent(user_query):
    with run(project_name="Refund Agent"):
        # 1. User input
        emit("user.input", {"text": user_query})
        
        # 2. Retrieval
        emit("retrieval.started", {"query": "refund policy"})
        documents = search_database("refund policy")
        emit("retrieval.result", {"documents": documents, "scores": [0.95]})
        
        # 3. Context injection
        emit("context.injected", {
            "blocks": [
                {"name": "Policy", "content": documents[0]["content"]},
                {"name": "User", "content": user_query}
            ]
        })
        
        # 4. Prompt assembly
        prompt = f"Based on the policy: {documents[0]['content']}\n\nUser: {user_query}"
        emit("prompt.assembled", {"text": prompt})
        
        # 5. Model call (any model: ChatGPT, Gemini, Claude, etc.)
        emit("model.request", {"model": "gpt-4", "prompt": prompt})
        response = call_llm(prompt)
        emit("model.response", {"text": response})
        
        # 6. Tool call
        emit("tool.called", {"name": "approve_refund", "arguments": {"order": "12345"}})
        result = approve_refund("12345")
        emit("tool.result", {"output": result})
        
        return response
Event Types Reference
Event Type	When to Use
user.input	When receiving user input
retrieval.started	When starting a retrieval query
retrieval.result	When retrieval returns results
context.injected	When injecting context into the prompt
prompt.assembled	When the final prompt is ready
model.request	Before calling the LLM
model.response	After receiving the LLM response
tool.called	Before calling a tool
tool.result	After receiving the tool result
memory.read	When reading from memory
memory.write	When writing to memory
memory.delete	When deleting from memory
state.snapshot	When capturing a state snapshot
Framework Integrations
OpenAI Agents SDK
Installation:

bash
pip install agent-devtools[openai-agents]
Usage:

python
from agents import Agent, Runner
from agent_devtools import run
from agent_devtools.integrations.openai_agents import trace_openai_agent

agent = Agent(
    name="Refund Assistant",
    instructions="Help users with refund requests."
)

with run(project_name="OpenAI Agent"):
    result = trace_openai_agent(
        agent,
        "Can I get a refund for order #12345?"
    )
What Gets Traced:

User input (automatic)

Model requests and responses

Tool calls and results

LangGraph / LangChain
Installation:

bash
pip install agent-devtools[langgraph]
Usage:

python
from langgraph.graph import StateGraph, END
from agent_devtools import run
from agent_devtools.integrations.langgraph import trace_langgraph

def agent_node(state):
    return {"messages": state["messages"] + ["Agent processing..."]}

graph = StateGraph(State)
graph.add_node("agent", agent_node)
graph.set_entry_point("agent")
graph.set_finish_point("agent")
compiled = graph.compile()

with run(project_name="LangGraph Agent"):
    result = trace_langgraph(compiled, {"messages": []})
What Gets Traced:

Chain starts and ends (state snapshots)

LLM requests and responses

Tool calls and results

Prompt assembly

CrewAI
Installation:

bash
pip install agent-devtools[crewai]
Usage:

python
from crewai import Agent, Task, Crew
from agent_devtools import run
from agent_devtools.integrations.crewai import trace_crew

refund_agent = Agent(
    role="Refund Specialist",
    goal="Process refund requests accurately"
)

refund_task = Task(
    description="Process refund for order #12345",
    agent=refund_agent
)

crew = Crew(agents=[refund_agent], tasks=[refund_task])

with run(project_name="CrewAI Demo"):
    result = trace_crew(crew, inputs={"order": "12345"})
What Gets Traced:

Task execution

Agent steps

LLM calls (via LangChain integration)

Tool calls (via LangChain integration)

Custom Integration
To add support for a new framework or custom tracer:

Step 1: Create a Tracer Class
python
from agent_devtools.integrations.base import BaseTracer
from agent_devtools.events import EventType

class MyFrameworkTracer(BaseTracer):
    def __init__(self):
        super().__init__()
    
    def trace_step(self, step_name, input_data, output_data):
        self.emit(EventType.STATE_SNAPSHOT, {
            "step": step_name,
            "input": input_data,
            "output": output_data
        })
Step 2: Implement the Tracer
python
def trace_my_framework(framework_object, input_data):
    run_id = get_current_run_id()
    if not run_id:
        raise RuntimeError("No active run context found")
    
    tracer = MyFrameworkTracer()
    
    try:
        result = framework_object.run(input_data)
        tracer.trace_step("execution", input_data, result)
        return result
    except Exception as e:
        tracer.emit(EventType.RUN_FINISHED, {
            "status": "failed",
            "error": str(e)
        })
        raise
Step 3: Add to Integrations
python
# agent_devtools/integrations/__init__.py
from .my_framework import trace_my_framework

__all__ = ["trace_my_framework", ...]
Redaction
By default, sensitive keys are redacted:

python
SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "authorization"}
Custom Redactors
python
def custom_redactor(payload):
    if "email" in payload:
        payload["email"] = "***REDACTED***"
    if "ssn" in payload:
        payload["ssn"] = "***REDACTED***"
    return payload

with run(project_name="My Agent", redactors=[custom_redactor]):
    emit("user.input", {"email": "user@example.com", "ssn": "123-45-6789"})
    # Stored as: {"email": "***REDACTED***", "ssn": "***REDACTED***"}
Best Practices
Use the Context Manager: Always wrap your agent execution with with run(...):.

Emit Events at Key Points: The more events you emit, the better your debugging visibility.

Use Structured Payloads: Use consistent JSON structures for easier filtering and comparison.

Configure Redactors: Always redact sensitive data to protect user privacy.

Generate Fixtures: Export problematic runs as fixtures to share with your team or for regression testing.

Write Tests: Use the assertion engine to catch regressions early.

Troubleshooting
Module Not Found
bash
pip install agent-devtools[all]
No Active Run Context
If you get RuntimeError: No active run context found, ensure you are calling the tracer inside a with run(...): block.

Database Permission Errors
bash
mkdir -p ~/.agent-devtools
chmod 755 ~/.agent-devtools
Events Not Showing in UI
Verify the server is running: agent-devtools serve

Verify the UI is running: npm run dev

Check the database location: ls ~/.agent-devtools/store.db

Check the API: curl http://localhost:8787/runs

docs/user-guide.md
User Guide
A practical guide to using Agent DevTools for debugging AI agents.

Quick Start
Step 1: Install
bash
cd agent-devtools/packages/python-sdk
poetry install
Step 2: Start the Debug Server
bash
poetry run agent-devtools serve
The server starts at http://localhost:8787

Step 3: Start the UI
bash
cd agent-devtools/apps/web
pnpm dev
The UI starts at http://localhost:5173

Step 4: Run Your Agent
python
from agent_devtools import run, EventType

def emit(event_type, payload):
    from agent_devtools import get_current_run_id
    from agent_devtools.transport import Transport
    from agent_devtools.events import Event
    run_id = get_current_run_id()
    if run_id:
        event = Event(run_id=run_id, event_type=event_type, payload=payload)
        Transport().write_event(event)

def my_agent():
    with run(project_name="My First Agent"):
        emit("user.input", {"text": "Hello!"})
        emit("prompt.assembled", {"text": "You said: Hello!"})
        emit("model.response", {"text": "Hello, user!"})

if __name__ == "__main__":
    my_agent()
Step 5: Inspect in UI
Open http://localhost:5173 and click on your run.

UI Navigation
Run List
The landing page displays all runs. Each row shows:

Column	Description
Project	The name you gave to the run
Status	completed, failed, or running
Created	Timestamp of execution
Duration	Execution time in milliseconds
Actions	Click "Inspect" to open the run
Run Detail View
Replay Tab
Shows a chronological timeline of all events.

Use Cases:

Understand the sequence of operations

Verify that events occurred in the expected order

Inspect payloads for debugging

Prompt Tab
Shows the assembled prompt that was sent to the model.

Use Cases:

Verify that the prompt contains the right context

Check for missing information

Debug prompt engineering issues

Context Tab
Displays all context injection events and state snapshots.

Use Cases:

Verify that the right context was injected

Check the content of context blocks

Debug state transitions in LangGraph

Retrieval Tab
Shows retrieval queries, results, and relevance scores.

Use Cases:

Verify that the right documents were retrieved

Check relevance scores

Debug retrieval quality issues

Memory Tab
Displays memory read, write, and delete operations.

Use Cases:

Verify that memory contains the expected values

Debug memory-related issues (stale data, missing data)

Track memory changes over time

Tools Tab
Shows tool calls and their results.

Use Cases:

Verify that tools were called with the right arguments

Check tool outputs

Debug tool selection issues

Diff Tab
Compare two runs side-by-side.

Use Cases:

Compare a successful run with a failed run

Identify what changed between two executions

Debug regression issues

Behavior Diff
The Diff feature is the most powerful tool in Agent DevTools.

How to Use
Open any run

Navigate to the Diff tab

Select Run A (baseline) and Run B (comparison)

Click "Compare"

What You See
Differences are categorized and color-coded:

Type	Color	Meaning
Added	Green	Value exists in B but not in A
Removed	Red	Value exists in A but not in B
Changed	Yellow	Value differs between A and B
Example: Stale Memory Bug
The examples/refund_agent/ demo demonstrates a classic bug:

Correct Run: Memory contains "Refund policy: 30 days"

Faulty Run: Memory contains "Refund policy: 14 days" (stale)

The Diff tab immediately shows the difference in the Prompt category, making the bug obvious.

Testing with Assertions
Creating a Test
Create a JSON test file:

json
{
  "name": "Refund Policy Test",
  "fixture_path": "fixtures/correct_run.json",
  "assertions": [
    {
      "type": "tool_called",
      "tool_name": "approve_refund"
    },
    {
      "type": "context_block_present",
      "block_name": "Policy",
      "contains": "30 days"
    },
    {
      "type": "prompt_contains",
      "text": "refund"
    }
  ]
}
Running Tests
bash
agent-devtools test tests/ --verbose
Available Assertions
Assertion Type	Description	Required Parameters
event_present	Event exists	event_type, payload_match (optional)
event_absent	Event does not exist	event_type, payload_match (optional)
context_block_present	Context block exists	block_name, contains (optional)
prompt_contains	Prompt contains text	text
tool_called	Tool was called	tool_name
tool_not_called	Tool was not called	tool_name
CI/CD Integration
bash
agent-devtools test tests/ --json > test_results.json
Exit code is 0 if all tests pass, 1 if any fail.

Exporting and Importing Fixtures
Export a Run
bash
agent-devtools export <run_id> --output fixture.json
Import a Run
bash
curl -X POST http://localhost:8787/runs/import -H "Content-Type: application/json" -d @fixture.json
Use Cases
Bug Reporting: Export a problematic run and share it with your team

Regression Testing: Export a "golden" run and use it in tests

Backup: Export important runs for long-term storage

CLI Reference
agent-devtools serve
Start the debug server.

bash
agent-devtools serve [--host HOST] [--port PORT]
agent-devtools list
List all runs.

bash
agent-devtools list
agent-devtools export
Export a run as JSON.

bash
agent-devtools export RUN_ID [--output FILE]
agent-devtools test
Run assertion tests.

bash
agent-devtools test PATH [--verbose] [--json]
Configuration
Database Location
Default: ~/.agent-devtools/store.db

Override:

bash
export AGENT_DEVTOOLS_DB_PATH=/custom/path/store.db
Redaction
Sensitive keys are automatically redacted:

python
SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "authorization"}
Custom redactors can be added:

python
def my_redactor(payload):
    if "email" in payload:
        payload["email"] = "***REDACTED***"
    return payload

with run(project_name="My Agent", redactors=[my_redactor]):
    # ...
Troubleshooting
No Runs Found
Ensure your agent is calling with run(...): and emitting events.

Check the database location: ls ~/.agent-devtools/store.db

Verify the server is running: agent-devtools serve

Events Not Showing in UI
Check the server logs for errors.

Verify the API endpoint: curl http://localhost:8787/runs

Ensure the UI is pointed to the correct server (default: localhost:8787).

CORS Errors
The server has CORS enabled by default. If you're running the UI on a different port, it should work out of the box.

Database Locked
SQLite can sometimes be locked if multiple processes write simultaneously. Agent DevTools is designed for single-user local use, so this should be rare.

Module Not Found
If you get ModuleNotFoundError: No module named 'agent_devtools', install the SDK:

bash
cd packages/python-sdk
pip install -e .
Best Practices
Wrap Your Agent: Always use with run(...): for every execution.

Emit Events Liberally: More events = better debugging visibility.

Use Descriptive Project Names: This helps identify runs in the UI.

Export Important Runs: Save runs that represent important behavior.

Write Tests: Use the assertion engine to prevent regressions.

Redact Sensitive Data: Always configure redactors for production data.

Use the Diff Tab: It's the most efficient way to debug regression issues.

Run the Demo: The refund_agent example demonstrates the power of the tool.

Example Workflows
Debugging a Failed Run
Find the failed run in the Run List

Open the Replay tab and find the last event before failure

Open the Prompt tab to see what the model received

Open the Context tab to verify context injection

Open the Retrieval tab to check retrieved documents

If the run was previously successful, use the Diff tab to compare

Regression Testing
Export a successful run: agent-devtools export <id> --output golden.json

Write a test with assertions on the golden run

Run the test after every change: agent-devtools test tests/

If the test fails, inspect the diff to identify the regression

Performance Investigation
Check run duration in the Run List

Open the Replay tab and look for unusual delays between events

Check the Retrieval tab for slow queries

Check the Tools tab for slow tool calls

Support
Issues: GitHub Issues

Documentation: docs/

Examples: examples/

Agent DevTools - Because understanding your agent shouldn't be a black box.