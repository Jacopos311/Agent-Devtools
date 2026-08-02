"""
LangChain adapter: a ``BaseCallbackHandler`` that bridges LangChain's
callback events into the agent-devtools append-only event store.

Usage
-----

    from agent_devtools import trace
    from agent_devtools.adapters import LangChainTraceHandler

    with trace.run("my-agent") as run:
        handler = LangChainTraceHandler(run=run)
        chain.invoke({"question": "..."}, config={"callbacks": [handler]})

Or standalone (the handler creates and finishes its own run):

    handler = LangChainTraceHandler(agent_name="my-agent")
    chain.invoke({"question": "..."}, config={"callbacks": [handler]})

The handler maps LangChain's callback events to agent-devtools events:

    on_chain_start      -> user.input (for the root chain)
    on_llm_start        -> prompt.assembled
    on_llm_end          -> model.response
    on_tool_start       -> tool.call
    on_tool_end         -> tool.result
    on_retriever_start  -> retrieval.query
    on_retriever_end    -> retrieval.result
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from ..store import TraceStore, default_db_path
from ..trace import Run

try:  # langchain-core is an optional dependency
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.documents import Document
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import LLMResult
except ImportError:  # pragma: no cover
    BaseCallbackHandler = object  # type: ignore[assignment,misc]
    Document = object  # type: ignore[assignment,misc]
    BaseMessage = object  # type: ignore[assignment,misc]
    LLMResult = object  # type: ignore[assignment,misc]


def _message_to_dict(message: Any) -> dict:
    """Convert a LangChain BaseMessage (or plain dict) to a serializable dict."""
    if isinstance(message, dict):
        return message
    if isinstance(message, BaseMessage):
        return {"role": message.type, "content": message.content}
    return {"content": str(message)}


def _document_to_dict(doc: Any) -> dict:
    """Convert a LangChain Document to a serializable dict."""
    if isinstance(doc, Document):
        return {
            "id": doc.id,
            "content": doc.page_content,
            "metadata": doc.metadata,
        }
    if isinstance(doc, dict):
        return doc
    return {"content": str(doc)}


def _extract_text(value: Any) -> str:
    """Best-effort extraction of a human-readable string from a LangChain value."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, BaseMessage):
        return str(value.content)
    if isinstance(value, Document):
        return value.page_content
    if isinstance(value, dict):
        return str(value)
    return str(value)


class LangChainTraceHandler(BaseCallbackHandler):
    """A LangChain ``BaseCallbackHandler`` that records events into
    agent-devtools' append-only SQLite store.

    Pass an existing ``Run`` handle (from ``trace.run(...)``) to attach to
    an already-open run, or let the handler create and manage its own run
    by passing ``agent_name`` (and optionally ``run_id`` / ``db_path``).
    """

    # LangChain calls handlers on the same thread as the run, but we keep
    # this flag for clarity / future async support.
    raise_error = False

    def __init__(
        self,
        run: Optional[Run] = None,
        *,
        agent_name: Optional[str] = None,
        run_id: Optional[str] = None,
        db_path: Optional[str] = None,
        store: Optional[TraceStore] = None,
    ) -> None:
        if run is None and agent_name is None:
            raise ValueError(
                "LangChainTraceHandler requires either a `run` handle "
                "(from trace.run(...)) or an `agent_name` to create one."
            )
        self._run = run
        self._agent_name = agent_name
        self._run_id = run_id
        self._db_path = db_path
        self._store = store
        self._owns_run = run is None
        self._root_chain_seen = False
        self._tool_names: dict[str, str] = {}

    # -- run lifecycle -------------------------------------------------

    def _ensure_run(self) -> Run:
        """Return the attached Run, creating one if this handler owns it."""
        if self._run is not None:
            return self._run
        store = self._store or TraceStore(self._db_path or default_db_path())
        run_id = self._run_id or f"{self._agent_name}-{uuid.uuid4().hex[:8]}"
        store.create_run(run_id, self._agent_name, {"framework": "langchain"})
        self._run = Run(store, run_id, self._agent_name)
        return self._run

    def _finish_run(self, status: str = "ok") -> None:
        if self._owns_run and self._run is not None:
            self._run.store.finish_run(self._run.run_id, status)

    # -- chains ---------------------------------------------------------

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        # Only the root chain (no parent) is treated as the user input.
        if parent_run_id is None and not self._root_chain_seen:
            self._root_chain_seen = True
            name = (serialized or {}).get("name") or "chain"
            run.input(
                inputs,
                chain=name,
                run_id=str(run_id),
                tags=tags or [],
                metadata=metadata or {},
            )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        # The root chain's end is the run's output.
        if parent_run_id is None:
            run = self._ensure_run()
            run.output(outputs, run_id=str(run_id))
            self._finish_run("ok")

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        if parent_run_id is None:
            run = self._ensure_run()
            run.log_event("chain.error", {"run_id": str(run_id), "error": str(error)})
            self._finish_run("error")

    # -- LLM / chat model ------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        name = (serialized or {}).get("name") or "llm"
        run.prompt(
            system=None,
            messages=[{"role": "user", "content": p} for p in prompts],
            model=name,
            run_id=str(run_id),
            tags=tags or [],
            metadata=metadata or {},
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        name = (serialized or {}).get("name") or "chat_model"
        # messages is a list of message lists (one per prompt); flatten.
        flat = [m for group in messages for m in group]
        run.prompt(
            system=None,
            messages=[_message_to_dict(m) for m in flat],
            model=name,
            run_id=str(run_id),
            tags=tags or [],
            metadata=metadata or {},
        )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        # Extract the first generation's text.
        text = ""
        if response.generations:
            first = response.generations[0]
            if first:
                text = _extract_text(first[0].text if hasattr(first[0], "text") else first[0])
        run.output(
            text,
            run_id=str(run_id),
            llm_output=response.llm_output or {},
            tags=tags or [],
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        run.log_event("model.error", {"run_id": str(run_id), "error": str(error)})

    # -- tools -----------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        inputs: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        name = (serialized or {}).get("name") or "tool"
        self._tool_names[str(run_id)] = name
        run.log_event("tool.call", {
            "name": name,
            "args": inputs or {"input": input_str},
            "run_id": str(run_id),
            "tags": tags or [],
            "metadata": metadata or {},
        })

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        name = self._tool_names.pop(str(run_id), "")
        run.log_event("tool.result", {
            "name": name,
            "result": _extract_text(output),
            "run_id": str(run_id),
        })

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        run.log_event("tool.error", {"run_id": str(run_id), "error": str(error)})

    # -- retrievers ------------------------------------------------------

    def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        name = (serialized or {}).get("name") or "retriever"
        run.log_event("retrieval.query", {
            "query": query,
            "retriever": name,
            "run_id": str(run_id),
            "tags": tags or [],
            "metadata": metadata or {},
        })

    def on_retriever_end(
        self,
        documents: list[Document],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        # We need the query; it was stored in the retrieval.query event.
        # Reconstruct from the last retrieval.query event for this run.
        query = ""
        events = run.store.get_events_by_types(run.run_id, ["retrieval.query"])
        if events:
            query = events[-1].payload.get("query", "")
        results = [_document_to_dict(d) for d in documents]
        run.log_event("retrieval.result", {
            "query": query,
            "results": results,
            "run_id": str(run_id),
        })

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        run = self._ensure_run()
        run.log_event("retrieval.error", {"run_id": str(run_id), "error": str(error)})