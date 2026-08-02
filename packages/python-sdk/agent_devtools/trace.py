"""
The primary ingestion path: manual, explicit instrumentation from inside
agent code. No trace export step, no adapter to write first -- import this,
wrap the run, and the local debugger has everything on the next request.

    from agent_devtools import trace

    with trace.run("refund-agent") as run:
        run.input(user_message)
        run.retrieval(query, results)
        run.context_block(source="memory", key="pricing", content=text)
        run.prompt(system=system_prompt, messages=messages)
        run.tool_call(name="lookup_order", args={"id": 42}, result={"status": "ok"})
        run.memory_write(key="last_price", value="19.99")
        run.output(response_text)
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Optional

from .redaction import redact
from .store import TraceStore, default_db_path

_default_store: Optional[TraceStore] = None


def _get_store(db_path: Optional[str] = None) -> TraceStore:
    global _default_store
    if db_path:
        return TraceStore(db_path)
    if _default_store is None:
        _default_store = TraceStore(default_db_path())
    return _default_store


class Run:
    """Handle returned by `trace.run(...)`; one logging method per event kind."""

    def __init__(self, store: TraceStore, run_id: str, agent_name: str):
        self.store = store
        self.run_id = run_id
        self.agent_name = agent_name

    def _log(self, event_type: str, payload: dict) -> None:
        self.store.log_event(self.run_id, event_type, redact(payload))

    # -- conversation & retrieval -----------------------------------

    def input(self, message: Any, **meta) -> None:
        self._log("user.input", {"message": message, **meta})

    def retrieval(self, query: str, results: list, **meta) -> None:
        """`results` is a list of dicts, e.g.
        {"id": "...", "content": "...", "source": "memory|doc|...",
         "score": 0.83, "rank": 1, "selected": True}
        """
        self._log("retrieval.query", {"query": query, **meta})
        self._log("retrieval.result", {"query": query, "results": results})

    # -- prompt & context provenance ---------------------------------

    def context_block(self, source: str, content: Any, key: Optional[str] = None,
                       order: Optional[int] = None, **meta) -> None:
        """One block of injected context, tagged with where it came from
        (memory, doc, tool result, system policy, developer instruction...)."""
        self._log("context.block", {
            "source": source, "key": key, "content": content, "order": order, **meta,
        })

    def prompt(self, system: Optional[str] = None, messages: Optional[list] = None,
               context: Optional[list] = None, **meta) -> None:
        """The final assembled model input -- the thing the model actually saw."""
        self._log("prompt.assembled", {
            "system": system, "messages": messages or [], "context": context or [], **meta,
        })

    # -- tools ---------------------------------------------------------

    def tool_call(self, name: str, args: Optional[dict] = None, result: Any = None,
                  error: Optional[str] = None, **meta) -> None:
        self._log("tool.call", {"name": name, "args": args or {}, **meta})
        if result is not None or error is not None:
            self._log("tool.result", {"name": name, "result": result, "error": error})

    # -- memory ----------------------------------------------------------

    def memory_read(self, key: str, value: Any, **meta) -> None:
        self._log("memory.read", {"key": key, "value": value, **meta})

    def memory_write(self, key: str, value: Any, **meta) -> None:
        self._log("memory.write", {"key": key, "value": value, **meta})

    def memory_update(self, key: str, old_value: Any, new_value: Any, **meta) -> None:
        self._log("memory.update", {"key": key, "old_value": old_value, "new_value": new_value, **meta})

    def memory_delete(self, key: str, **meta) -> None:
        self._log("memory.delete", {"key": key, **meta})

    # -- state & output --------------------------------------------------

    def state_snapshot(self, state: Any, **meta) -> None:
        self._log("state.snapshot", {"state": state, **meta})

    def output(self, response: Any, **meta) -> None:
        self._log("model.response", {"response": response, **meta})

    # -- debug assertions ---------------------------------------------

    def assert_that(self, name: str, passed: bool, details: Optional[str] = None) -> None:
        self._log("assertion.passed" if passed else "assertion.failed",
                   {"name": name, "details": details})

    # -- escape hatch --------------------------------------------------

    def log_event(self, event_type: str, payload: dict) -> None:
        """Fixture/portable event format is not the primary path, but any
        raw event type can be recorded here for adapters/bridges."""
        self._log(event_type, payload)


@contextmanager
def run(agent_name: str, run_id: Optional[str] = None, db_path: Optional[str] = None,
        metadata: Optional[dict] = None):
    """Open a new run. Everything logged inside the `with` block belongs to
    this run, whether the block succeeds, raises, or ends normally."""
    store = _get_store(db_path)
    run_id = run_id or f"{agent_name}-{uuid.uuid4().hex[:8]}"
    store.create_run(run_id, agent_name, metadata)
    handle = Run(store, run_id, agent_name)
    status = "ok"
    try:
        yield handle
    except Exception:
        status = "error"
        raise
    finally:
        store.finish_run(run_id, status)
