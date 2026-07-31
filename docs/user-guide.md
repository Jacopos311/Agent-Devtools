# User Guide

A practical guide to using Agent DevTools for debugging AI agents.

---

## Quick Start

### 1. Install

cd agent-devtools/packages/python-sdk
poetry install

### 2. Start the Debug Server

poetry run agent-devtools serve

The server starts at http://localhost:8787

### 3. Start the UI

cd agent-devtools/apps/web
pnpm dev

The UI starts at http://localhost:5173

### 4. Run Your Agent

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

### 5. Inspect in UI

Open http://localhost:5173 and click on your run.

---

## UI Navigation

### Run List

The landing page displays all runs. Each row shows:
- Project Name – The name you gave to the run
- Status – completed, failed, or running
- Created – Timestamp of execution
- Duration – Execution time in milliseconds
- Actions – Click "Inspect" to open the run

### Run Detail View

#### Replay Tab

Shows a chronological timeline of all events. Each event displays:
- Timestamp
- Event type
- Payload (expandable by clicking the event)

Use Cases:
- Understand the sequence of operations
- Verify that events occurred in the expected order
- Inspect payloads for debugging

#### Prompt Tab

Shows the assembled prompt that was sent to the model. If multiple prompts were sent, the most recent one is displayed.

Use Cases:
- Verify that the prompt contains the right context
- Check for missing information
- Debug prompt engineering issues

#### Context Tab

Displays all context injection events and state snapshots.

Use Cases:
- Verify that the right context was injected
- Check the content of context blocks
- Debug state transitions in LangGraph

#### Retrieval Tab

Shows retrieval queries, results, and relevance scores.

Use Cases:
- Verify that the right documents were retrieved
- Check relevance scores
- Debug retrieval quality issues

#### Memory Tab

Displays memory read, write, and delete operations.

Use Cases:
- Verify that memory contains the expected values
- Debug memory-related issues (stale data, missing data)
- Track memory changes over time

#### Tools Tab

Shows tool calls and their results.

Use Cases:
- Verify that tools were called with the right arguments
- Check tool outputs
- Debug tool selection issues

#### Diff Tab

Compare two runs side-by-side.

Use Cases:
- Compare a successful run with a failed run
- Identify what changed between two executions
- Debug regression issues

---

## Behavior Diff

The Diff feature is the most powerful tool in Agent DevTools. It allows you to compare any two runs and see exactly what changed.

### How to Use

1. Open any run
2. Navigate to the Diff tab
3. Select Run A (baseline) and Run B (comparison)
4. Click "Compare"

### What You See

Differences are categorized and color-coded:

| Type | Color | Meaning |
|------|-------|---------|
| Added | Green | Value exists in B but not in A |
| Removed | Red | Value exists in A but not in B |
| Changed | Yellow | Value differs between A and B |

### Example: Stale Memory Bug

The examples/refund_agent/ demo demonstrates a classic bug:
- Correct Run: Memory contains "Refund policy: 30 days"
- Faulty Run: Memory contains "Refund policy: 14 days" (stale)

The Diff tab immediately shows the difference in the Prompt category, making the bug obvious.

---

## Testing with Assertions

### Creating a Test

Create a JSON test file:

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

### Running Tests

agent-devtools test tests/ --verbose

### Available Assertions

| Assertion Type | Description | Required Parameters |
|----------------|-------------|---------------------|
| event_present | Event exists | event_type, payload_match (optional) |
| event_absent | Event does not exist | event_type, payload_match (optional) |
| context_block_present | Context block exists | block_name, contains (optional) |
| prompt_contains | Prompt contains text | text |
| tool_called | Tool was called | tool_name |
| tool_not_called | Tool was not called | tool_name |

### CI/CD Integration

agent-devtools test tests/ --json > test_results.json

Exit code is 0 if all tests pass, 1 if any fail.

---

## Exporting and Importing Fixtures

### Export a Run

agent-devtools export <run_id> --output fixture.json

### Import a Run

curl -X POST http://localhost:8787/runs/import -H "Content-Type: application/json" -d @fixture.json

### Use Cases

- Bug Reporting: Export a problematic run and share it with your team
- Regression Testing: Export a "golden" run and use it in tests
- Backup: Export important runs for long-term storage

---

## CLI Reference

### agent-devtools serve

Start the debug server.

agent-devtools serve [--host HOST] [--port PORT]

### agent-devtools list

List all runs.

agent-devtools list

### agent-devtools export

Export a run as JSON.

agent-devtools export RUN_ID [--output FILE]

### agent-devtools test

Run assertion tests.

agent-devtools test PATH [--verbose] [--json]

---

## Configuration

### Database Location

Default: ~/.agent-devtools/store.db

Override:

export AGENT_DEVTOOLS_DB_PATH=/custom/path/store.db

### Redaction

Sensitive keys are automatically redacted:

SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "authorization"}

Custom redactors can be added:

def my_redactor(payload):
    if "email" in payload:
        payload["email"] = "***REDACTED***"
    return payload

with run(project_name="My Agent", redactors=[my_redactor]):
    # ...

---

## Troubleshooting

### No Runs Found

1. Ensure your agent is calling with run(...): and emitting events.
2. Check the database location: ls ~/.agent-devtools/store.db
3. Verify the server is running: agent-devtools serve

### Events Not Showing in UI

1. Check the server logs for errors.
2. Verify the API endpoint: curl http://localhost:8787/runs
3. Ensure the UI is pointed to the correct server (default: localhost:8787).

### CORS Errors

The server has CORS enabled by default. If you're running the UI on a different port, it should work out of the box.

### Database Locked

SQLite can sometimes be locked if multiple processes write simultaneously. Agent DevTools is designed for single-user local use, so this should be rare.

### Module Not Found

If you get ModuleNotFoundError: No module named 'agent_devtools', install the SDK:

cd packages/python-sdk
pip install -e .

---

## Best Practices

1. Wrap Your Agent: Always use with run(...): for every execution.

2. Emit Events Liberally: More events = better debugging visibility.

3. Use Descriptive Project Names: This helps identify runs in the UI.

4. Export Important Runs: Save runs that represent important behavior.

5. Write Tests: Use the assertion engine to prevent regressions.

6. Redact Sensitive Data: Always configure redactors for production data.

7. Use the Diff Tab: It's the most efficient way to debug regression issues.

8. Run the Demo: The refund_agent example demonstrates the power of the tool.

---

## Example Workflows

### Debugging a Failed Run

1. Find the failed run in the Run List
2. Open the Replay tab and find the last event before failure
3. Open the Prompt tab to see what the model received
4. Open the Context tab to verify context injection
5. Open the Retrieval tab to check retrieved documents
6. If the run was previously successful, use the Diff tab to compare

### Regression Testing

1. Export a successful run: agent-devtools export <id> --output golden.json
2. Write a test with assertions on the golden run
3. Run the test after every change: agent-devtools test tests/
4. If the test fails, inspect the diff to identify the regression

### Performance Investigation

1. Check run duration in the Run List
2. Open the Replay tab and look for unusual delays between events
3. Check the Retrieval tab for slow queries
4. Check the Tools tab for slow tool calls

---

## Support

- Issues: GitHub Issues
- Documentation: docs/
- Examples: examples/

---

*Agent DevTools - Because understanding your agent shouldn't be a black box.*