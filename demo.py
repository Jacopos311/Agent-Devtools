"""
AgentScope / agent-devtools demo with Groq -- zero-config.

This script:

1. Checks for a ``GROQ_API_KEY`` in the environment and prints clear
   setup instructions if it is missing (free key at console.groq.com).
2. Starts the local agent-devtools Dashboard server and opens it in the
   browser automatically.
3. Runs a tiny conversational loop over Groq (llama-3.3-70b-versatile)
   with a simple in-memory "memory" store, tracing every model call into
   the Dashboard.

Run it:
    $env:GROQ_API_KEY="gsk_..."
    OR
    export GROQ_API_KEY="gsk_..."
    pip install 'agent-devtools[groq]'
    python demo.py
"""

from __future__ import annotations

import os
import sys

# Make the in-repo SDK importable when running from this directory.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK_PATH = os.path.join(_REPO_ROOT, "packages", "python-sdk")
if os.path.isdir(_SDK_PATH) and _SDK_PATH not in sys.path:
    sys.path.insert(0, _SDK_PATH)

from agent_devtools import AgentDebugger
from agent_devtools.adapters.groq import GROQ_KEY_HINT, check_groq_api_key

MODEL_NAME = "llama-3.3-70b-versatile"


class SimpleMemory:
    """A tiny in-memory key/value store used to demo memory tracing."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


def main() -> None:
    # 1) Groq API key check -------------------------------------------
    if not check_groq_api_key():
        print(GROQ_KEY_HINT, file=sys.stderr)
        sys.exit(1)

    # 2) Zero-config debugger: starts the server + opens the Dashboard.
    debugger = AgentDebugger(name="groq-demo")
    debugger.start()

    # 3) Fully-traced Groq LLM (llama-3.3-70b-versatile).
    llm = debugger.create_groq_llm(model_name=MODEL_NAME)

    # Tiny memory store that gets traced on every read/write.
    memory = SimpleMemory()
    memory.set("user_name", "Alice")

    print(f"\nAgentScope demo started. Model: {MODEL_NAME}")
    print("Dashboard: http://127.0.0.1:4173  (opened in your browser)\n")
    print("Type 'exit' or 'quit' to stop.\n")

    # 4) Conversation loop with memory + tracing.
    with debugger.run("groq-demo") as run:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break

            if user_input.lower() in {"exit", "quit"}:
                print("Bye!")
                break

            # Trace the user message.
            run.input(user_input)

            # Read from memory and trace the read.
            user_name = memory.get("user_name")
            run.memory_read(key="user_name", value=user_name)

            # Build a context block from memory and trace it.
            memory_context = f"The user's name is {user_name}."
            run.context_block(source="memory", key="user_name", content=memory_context)

            # Model call (fully traced via the LangChain callback handler:
            # on_chat_model_start -> prompt.assembled, on_llm_end -> model.response).
            answer = llm.invoke(
                [
                    {"role": "system", "content": "You are a helpful assistant with a short memory."},
                    {"role": "user", "content": memory_context},
                    {"role": "user", "content": user_input},
                ]
            )

            # If the user told us their name, store it in memory and trace.
            if "my name is" in user_input.lower():
                new_name = user_input.lower().split("my name is")[-1].strip().title()
                old = memory.get("user_name")
                memory.set("user_name", new_name)
                run.memory_update(key="user_name", old_value=old, new_value=new_name)
                print(f"[memory] user_name updated: {old!r} -> {new_name!r}")

            print(f"Groq: {answer.content}")

    print("\nDemo finished.")
    print("Your run was traced -- check the Dashboard (http://127.0.0.1:4173).")
    print("The data is stored locally in .agent_devtools/trace.db")


if __name__ == "__main__":
    main()