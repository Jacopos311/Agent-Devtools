"""Quick verification for the Groq integration (no API key needed)."""

from __future__ import annotations

import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK_PATH = os.path.join(_REPO_ROOT, "packages", "python-sdk")
if os.path.isdir(_SDK_PATH) and _SDK_PATH not in sys.path:
    sys.path.insert(0, _SDK_PATH)

from agent_devtools import AgentDebugger
from agent_devtools.adapters.groq import (
    DEFAULT_GROQ_MODEL,
    GROQ_KEY_HINT,
    check_groq_api_key,
)


def main() -> None:
    # 1. Verify the default model + key check
    print(f"Default Groq model: {DEFAULT_GROQ_MODEL}")
    print(f"Key present (env): {check_groq_api_key()}")

    # 2. Create an AgentDebugger on a temp DB, no browser.
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "test.db")
    debugger = AgentDebugger(name="test-groq", db_path=db, auto_open_browser=False, port=4199)
    debugger.start()
    print(f"Store db: {debugger.store.db_path}")
    print("Server started OK")

    # 3. Trace a run with memory events.
    with debugger.run("test-groq") as run:
        run.input("Hello groq")
        run.memory_read(key="user_name", value="Alice")
        run.context_block(source="memory", key="user_name", content="The user name is Alice.")
        run.prompt(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            model="llama-3.3-70b-versatile",
        )
        run.output("Hi Alice!")
    print("Run traced OK")

    # 4. Verify the events were persisted.
    runs = debugger.store.list_runs()
    print(f"Runs in store: {len(runs)}")
    for r in runs:
        events = debugger.store.get_events(r["id"])
        print(f"Run {r['id']}: {len(events)} events, types={[e.type for e in events]}")

    # 5. Verify the factory raises the friendly error without a key.
    try:
        debugger.create_groq_llm()
        print("ERROR: expected GroqApiKeyError but got no exception")
        sys.exit(1)
    except Exception as exc:
        print(f"create_groq_llm raised as expected: {type(exc).__name__} {exc}")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()