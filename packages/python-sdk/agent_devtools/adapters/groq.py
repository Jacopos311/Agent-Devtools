"""
Groq integration for agent-devtools.

Native support for ``langchain-groq``: wraps a ``ChatGroq`` instance so
every model call is automatically traced into the agent-devtools store.

The tracing reuses ``LangChainTraceHandler``:

- messages sent to the model  -> ``prompt.assembled``
- model output text           -> ``model.response``  (via ``on_llm_end``)

``TracedGroq`` additionally manages the run lifecycle for *bare* model
invocations (a ``ChatGroq`` used directly does not emit chain events, so
nobody would otherwise finish the run).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from .langchain import LangChainTraceHandler

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

GROQ_KEY_URL = "https://console.groq.com/keys"

GROQ_KEY_HINT = f"""\
GROQ_API_KEY not found in the environment.

Get a free Groq API key -- no credit card required -- at:
    {GROQ_KEY_URL}

Then export it and run the demo again:

    export GROQ_API_KEY="gsk_..."
    python demo.py
"""


class GroqApiKeyError(RuntimeError):
    """Raised when no Groq API key is available."""


def check_groq_api_key(groq_api_key: Optional[str] = None) -> bool:
    """Return True if a Groq API key is available (env var or explicit)."""
    key = (groq_api_key or os.environ.get("GROQ_API_KEY") or "").strip()
    return bool(key)


def _require_groq_api_key(groq_api_key: Optional[str] = None) -> str:
    key = (groq_api_key or os.environ.get("GROQ_API_KEY") or "").strip()
    if not key:
        print(GROQ_KEY_HINT, file=sys.stderr)
        raise GroqApiKeyError("GROQ_API_KEY is not set")
    return key


class TracedGroq:
    """A traced wrapper around ``langchain_groq.ChatGroq``.

    Every ``invoke`` / ``ainvoke`` / ``batch`` / ``abatch`` / ``stream``
    call records the messages sent to the model (``prompt.assembled``) and
    the model output (``model.response``) into the store attached to
    ``debugger``.

    Calls made inside an active ``debugger.run()`` block attach to that
    run; calls made outside create and finish their own run.

    Any attribute that is not overridden here (e.g. ``bind_tools``,
    ``with_structured_output``) is delegated to the underlying
    ``ChatGroq`` instance.
    """

    def __init__(
        self,
        llm: Any,
        debugger: Any,
        *,
        model_name: Optional[str] = None,
    ) -> None:
        self._llm = llm
        self._debugger = debugger
        self.model_name = (
            model_name
            or getattr(llm, "model_name", None)
            or DEFAULT_GROQ_MODEL
        )

    def __repr__(self) -> str:
        return f"TracedGroq(model={self.model_name!r})"

    # -- passthrough of non-traced attributes ------------------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)

    # -- tracing plumbing ---------------------------------------------

    def _trace_begin(self) -> tuple[Any, bool]:
        """Return ``(run, standalone)`` where *standalone* is True when the
        call created its own run (i.e. no active ``debugger.run()`` block)."""
        run = self._debugger._current_run()
        if run is not None:
            return run, False
        run = self._debugger._start_run(
            metadata={"provider": "groq", "model": self.model_name}
        )
        return run, True

    def _finish_if_standalone(self, run: Any, standalone: bool, status: str) -> None:
        if standalone:
            self._debugger._store.finish_run(run.run_id, status)

    def _with_handler(self, config: Optional[dict], run: Any) -> dict:
        handler = LangChainTraceHandler(run=run)
        callbacks = list((config or {}).get("callbacks", [])) + [handler]
        return {**(config or {}), "callbacks": callbacks}

    # -- traced methods -------------------------------------------------

    def invoke(self, input: Any, *, config: Optional[dict] = None, **kwargs: Any) -> Any:
        run, standalone = self._trace_begin()
        merged = self._with_handler(config, run)
        try:
            result = self._llm.invoke(input, config=merged, **kwargs)
        except Exception:
            self._finish_if_standalone(run, standalone, "error")
            raise
        self._finish_if_standalone(run, standalone, "ok")
        return result

    def ainvoke(self, input: Any, *, config: Optional[dict] = None, **kwargs: Any) -> Any:
        run, standalone = self._trace_begin()
        merged = self._with_handler(config, run)
        try:
            result = self._llm.ainvoke(input, config=merged, **kwargs)
        except Exception:
            self._finish_if_standalone(run, standalone, "error")
            raise
        self._finish_if_standalone(run, standalone, "ok")
        return result

    def batch(self, inputs: list, *, config: Optional[dict] = None, **kwargs: Any) -> list:
        run, standalone = self._trace_begin()
        merged = self._with_handler(config, run)
        try:
            results = self._llm.batch(inputs, config=merged, **kwargs)
        except Exception:
            self._finish_if_standalone(run, standalone, "error")
            raise
        self._finish_if_standalone(run, standalone, "ok")
        return results

    def abatch(self, inputs: list, *, config: Optional[dict] = None, **kwargs: Any) -> list:
        run, standalone = self._trace_begin()
        merged = self._with_handler(config, run)
        try:
            results = self._llm.abatch(inputs, config=merged, **kwargs)
        except Exception:
            self._finish_if_standalone(run, standalone, "error")
            raise
        self._finish_if_standalone(run, standalone, "ok")
        return results

    def stream(self, input: Any, *, config: Optional[dict] = None, **kwargs: Any):
        run, standalone = self._trace_begin()
        merged = self._with_handler(config, run)
        status = "ok"
        try:
            yield from self._llm.stream(input, config=merged, **kwargs)
        except Exception:
            status = "error"
            raise
        finally:
            self._finish_if_standalone(run, standalone, status)

    async def astream(self, input: Any, *, config: Optional[dict] = None, **kwargs: Any):
        run, standalone = self._trace_begin()
        merged = self._with_handler(config, run)
        status = "ok"
        try:
            async for chunk in self._llm.astream(input, config=merged, **kwargs):
                yield chunk
        except Exception:
            status = "error"
            raise
        finally:
            self._finish_if_standalone(run, standalone, status)


def wrap_groq(
    llm: Any,
    debugger: Any,
    *,
    model_name: Optional[str] = None,
) -> TracedGroq:
    """Wrap an existing ``langchain_groq.ChatGroq`` (or any compatible chat
    model) so every call is automatically traced into the debugger's store."""
    return TracedGroq(llm, debugger, model_name=model_name)


def create_groq_llm(
    debugger: Any,
    model_name: str = DEFAULT_GROQ_MODEL,
    *,
    groq_api_key: Optional[str] = None,
    **kwargs: Any,
) -> TracedGroq:
    """Create a traced ``langchain_groq.ChatGroq`` instance.

    Requires ``langchain-groq`` to be installed
    (``pip install 'agent-devtools[groq]'``) and a valid API key in
    ``GROQ_API_KEY`` (or passed via ``groq_api_key``).  Raises
    ``GroqApiKeyError`` -- after printing setup instructions -- when the
    key is missing.
    """
    api_key = _require_groq_api_key(groq_api_key)
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:  # pragma: no cover - depends on user env
        raise ImportError(
            "langchain-groq is required for Groq support. "
            "Install it with:  pip install 'agent-devtools[groq]'"
        ) from exc

    llm = ChatGroq(groq_api_key=api_key, model_name=model_name, **kwargs)
    return wrap_groq(llm, debugger, model_name=model_name)