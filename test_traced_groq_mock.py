"""End-to-end verification of TracedGroq using a real langchain-core fake chat model.

Uses ``FakeListChatModel`` (a real ``BaseChatModel`` subclass) so the full
LangChain callback path still fires (``on_chat_model_start`` /
``on_llm_end``) without needing a Groq API key.
"""

from __future__ import annotations

import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SDK_PATH = os.path.join(_REPO_ROOT, "packages", "python-sdk")
if os.path.isdir(_SDK_PATH) and _SDK_PATH not in sys.path:
    sys.path.insert(0, _SDK_PATH)

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from agent_devtools import AgentDebugger
from agent_devtools.adapters.groq import wrap_groq


def main() -> None:
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "trace.db")
    debugger = AgentDebugger(name="mock-groq", db_path=db, auto_open_browser=False, port=4188)

    fake = FakeListChatModel(responses=["Hello, Alice! How can I help you today?"])
    traced = wrap_groq(fake, debugger)
    print(f"Traced wrapper: {traced!r}")
    print(f"Model name propagated: {traced.model_name}")

    with debugger.run("mock-groq") as run:
        answer = traced.invoke(
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hi, my name is Bob"},
            ]
        )
    print(f"Answer: {answer.content}")

    runs = debugger.store.list_runs()
    assert runs, "expected at least one run"
    events = debugger.store.get_events(runs[0]["id"])
    types = [e.type for e in events]
    print(f"Event types: {types}")

    assert "prompt.assembled" in types, "expected prompt.assembled from on_chat_model_start"
    assert "model.response" in types, "expected model.response from on_llm_end"
    assert runs[0]["status"] == "ok", f"run should be ok, got {runs[0]['status']}"

    print("\nTRACED GROQ MOCK TEST PASSED")


if __name__ == "__main__":
    main()