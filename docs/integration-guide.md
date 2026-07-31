# Integration Guide

This guide explains how to integrate Agent DevTools with your AI agent framework.

---

## Overview

Agent DevTools provides two ways to instrument your agent:

1. Manual Instrumentation – Use the run() context manager and emit() function directly. Works with any Python code, including direct API calls to ChatGPT, Gemini, Claude, etc.

2. Framework Integrations – Use built-in tracers for popular frameworks (OpenAI Agents SDK, LangGraph, CrewAI). These automatically capture events.

---

## Manual Instrumentation

### Basic Setup

from agent_devtools import run, EventType

def my_agent(input_text):
    with run(project_name="My Agent"):
        # Your agent logic here
        result = ...
        return result

### Emitting Events

Inside the context manager, use the emit() function to log events:

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

### Complete Example

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

### Event Types Reference

| Event Type | When to Use |
|------------|-------------|
| user.input | When receiving user input |
| retrieval.started | When starting a retrieval query |
| retrieval.result | When retrieval returns results |
| context.injected | When injecting context into the prompt |
| prompt.assembled | When the final prompt is ready |
| model.request | Before calling the LLM |
| model.response | After receiving the LLM response |
| tool.called | Before calling a tool |
| tool.result | After receiving the tool result |
| memory.read | When reading from memory |
| memory.write | When writing to memory |
| memory.delete | When deleting from memory |
| state.snapshot | When capturing a state snapshot |

---

## Framework Integrations

### OpenAI Agents SDK

Installation:

pip install agent-devtools[openai-agents]

Usage:

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
- User input (automatic)
- Model requests and responses
- Tool calls and results

---

### LangGraph / LangChain

Installation:

pip install agent-devtools[langgraph]

Usage:

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
- Chain starts and ends (state snapshots)
- LLM requests and responses
- Tool calls and results
- Prompt assembly

---

### CrewAI

Installation:

pip install agent-devtools[crewai]

Usage:

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
- Task execution
- Agent steps
- LLM calls (via LangChain integration)
- Tool calls (via LangChain integration)

---

## Custom Integration

To add support for a new framework or custom tracer:

### 1. Create a Tracer Class

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

### 2. Implement the Tracer

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

### 3. Add to Integrations

# agent_devtools/integrations/__init__.py
from .my_framework import trace_my_framework

__all__ = ["trace_my_framework", ...]

---

## Redaction

By default, sensitive keys are redacted:

SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "authorization"}

### Custom Redactors

def custom_redactor(payload):
    if "email" in payload:
        payload["email"] = "***REDACTED***"
    if "ssn" in payload:
        payload["ssn"] = "***REDACTED***"
    return payload

with run(project_name="My Agent", redactors=[custom_redactor]):
    emit("user.input", {"email": "user@example.com", "ssn": "123-45-6789"})
    # Stored as: {"email": "***REDACTED***", "ssn": "***REDACTED***"}

---

## Best Practices

1. Use the Context Manager: Always wrap your agent execution with with run(...):.

2. Emit Events at Key Points: The more events you emit, the better your debugging visibility.

3. Use Structured Payloads: Use consistent JSON structures for easier filtering and comparison.

4. Configure Redactors: Always redact sensitive data to protect user privacy.

5. Generate Fixtures: Export problematic runs as fixtures to share with your team or for regression testing.

6. Write Tests: Use the assertion engine to catch regressions early.

---

## Troubleshooting

### Module Not Found

pip install agent-devtools[all]

### No Active Run Context

If you get RuntimeError: No active run context found, ensure you are calling the tracer inside a with run(...): block.

### Database Permission Errors

mkdir -p ~/.agent-devtools
chmod 755 ~/.agent-devtools

### Events Not Showing in UI

1. Verify the server is running: agent-devtools serve
2. Verify the UI is running: npm run dev
3. Check the database location: ls ~/.agent-devtools/store.db
4. Check the API: curl http://localhost:8787/runs