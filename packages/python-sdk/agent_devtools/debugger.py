"""
High-level AgentDebugger: zero-config entry point for agent-devtools.

    from agent_devtools import AgentDebugger
    from agent_devtools.adapters.groq import create_groq_llm

    debugger = AgentDebugger()          # starts the live server + opens the UI
    debugger.start()

    llm = create_groq_llm(debugger)     # traced ChatGroq (llama-3.3-70b-versatile)

    with debugger.run("groq-agent") as run:
        run.input("Hello")
        answer = llm.invoke("Hello")
        run.output(answer.content)
"""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser
from contextlib import contextmanager
from typing import Any, Optional

from .store import TraceStore, default_db_path
from .trace import Run

DEFAULT_UI_PORT = 4173
_DEFAULT_HOST = "127.0.0.1"


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


class AgentDebugger:
    """Zero-config wrapper around the agent-devtools stack.

    Owns the trace store and provides:

    - ``start()`` / ``open_ui()`` -- start the local debug server (FastAPI)
      on ``http://127.0.0.1:4173`` and open the Dashboard in the browser.
    - ``create_groq_llm(...)`` -- build a fully-traced ``ChatGroq``.
    - ``run(...)`` -- the ``trace.run(...)`` context manager (kept here so
      ``debugger.run()`` is the only API needed by demo scripts).

    The server is started in a background thread the first time
    ``start()`` is called; if a server is already running on the default
    port it is reused instead of being started twice.
    """

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        db_path: Optional[str] = None,
        host: str = _DEFAULT_HOST,
        port: int = DEFAULT_UI_PORT,
        auto_open_browser: bool = True,
    ) -> None:
        self.name = name or "agent-devtools"
        self.db_path = db_path or default_db_path()
        self.host = host
        self.port = port
        self.auto_open_browser = auto_open_browser
        self._store = TraceStore(self.db_path)
        self._server_thread: Optional[threading.Thread] = None
        self._server_started = False
        self._active_run: Optional[Run] = None

    # -- store / trace helpers ---------------------------------------

    @property
    def store(self) -> TraceStore:
        return self._store

    def _current_run(self) -> Optional[Run]:
        return self._active_run

    def _start_run(self, metadata: Optional[dict] = None) -> Run:
        """Create a new run that is *not* tied to a ``with`` block.

        Used by the Groq traced wrapper when a model call happens outside
        an active ``debugger.run()`` block; the run stays open until the
        caller finishes it (``store.finish_run``)."""
        import uuid

        run_id = f"{self.name}-{uuid.uuid4().hex[:8]}"
        self._store.create_run(run_id, self.name, metadata)
        return Run(self._store, run_id, self.name)

    @contextmanager
    def run(
        self,
        agent_name: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """Open a new run. Everything logged inside the ``with`` block
        belongs to this run, whether the block succeeds, raises, or ends
        normally. Nested ``debugger.run()`` blocks share the outermost one.

        When the run closes, the server is automatically started (and the
        browser opened) so the Dashboard immediately shows the fresh data.
        """
        if self._active_run is not None:
            existing = self._active_run
            try:
                yield existing
            finally:
                pass
            return

        import uuid

        run_id = run_id or f"{agent_name or self.name}-{uuid.uuid4().hex[:8]}"
        self._store.create_run(run_id, agent_name or self.name, metadata)
        handle = Run(self._store, run_id, agent_name or self.name)
        self._active_run = handle
        status = "ok"
        try:
            yield handle
        except Exception:
            status = "error"
            raise
        finally:
            self._store.finish_run(run_id, status)
            self._active_run = None
            if self.auto_open_browser:
                self.start(open_browser=True)

    # -- Groq integration ---------------------------------------------

    def create_groq_llm(
        self,
        model_name: str = "llama-3.3-70b-versatile",
        *,
        groq_api_key: Optional[str] = None,
        **kwargs: Any,
    ):
        """Create a fully-traced ``langchain_groq.ChatGroq`` instance.

        Requires ``langchain-groq`` and a ``GROQ_API_KEY`` (env var or
        ``groq_api_key=...``). Prints clear setup instructions if the key
        is missing. See ``agent_devtools.adapters.groq.create_groq_llm``.
        """
        from .adapters.groq import create_groq_llm as _factory

        return _factory(
            self,
            model_name=model_name,
            groq_api_key=groq_api_key,
            **kwargs,
        )

    def wrap_groq(self, llm: Any, *, model_name: Optional[str] = None):
        """Wrap an existing ``ChatGroq`` (or any compatible chat model) so
        every call is automatically traced into this debugger's store."""
        from .adapters.groq import wrap_groq as _wrap

        return _wrap(llm, self, model_name=model_name)

    # -- server lifecycle ----------------------------------------------

    def _ensure_server_started(self) -> None:
        if self._server_started:
            return

        if _port_is_free(self.host, self.port):
            # Start Uvicorn in a background thread.
            import uvicorn

            config = uvicorn.Config(
                "agent_devtools.server.main:app",
                host=self.host,
                port=self.port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(
                target=server.run,
                name="agent-devtools-server",
                daemon=True,
            )
            thread.start()
            self._server_thread = thread
            self._server_started = True
            print(
                f"agent-devtools: dashboard -> http://{self.host}:{self.port} "
                f"(db: {self.db_path})",
                file=sys.stderr,
            )
        else:
            # Someone (maybe us, maybe a previous `agent-devtools serve`)
            # is already listening; just reuse it.
            self._server_started = True
            self._warn_if_db_mismatch()
            print(
                f"agent-devtools: reusing existing server at "
                f"http://{self.host}:{self.port}",
                file=sys.stderr,
            )

    def _warn_if_db_mismatch(self) -> None:
        """If an existing server is already listening on our port, check
        which database it is serving and warn loudly when it differs from
        the one this debugger writes to.  A silent mismatch is the #1 cause
        of "my runs don't show up in the UI"."""
        import json
        import urllib.request

        try:
            with urllib.request.urlopen(
                f"http://{self.host}:{self.port}/api/health", timeout=2
            ) as resp:
                health = json.loads(resp.read())
        except Exception:
            # Server not responding yet (or not an agent-devtools server);
            # nothing useful to compare.
            return

        server_db = health.get("db", "")
        if not server_db:
            return

        # Normalize paths for comparison (resolve relative -> absolute).
        import os

        server_abs = os.path.abspath(server_db)
        mine_abs = os.path.abspath(self.db_path)
        if os.path.normcase(server_abs) == os.path.normcase(mine_abs):
            return

        print(
            f"\n"
            f"agent-devtools: WARNING -- database mismatch!\n"
            f"  The server on port {self.port} is serving:\n"
            f"    {server_abs}\n"
            f"  but this debugger writes to:\n"
            f"    {mine_abs}\n"
            f"  Runs you create now will NOT appear in the UI.\n"
            f"  Fix: stop the existing server and start it with the same\n"
            f"  database, e.g.  agent-devtools serve --db {mine_abs}\n",
            file=sys.stderr,
        )

    def open_ui(self) -> None:
        """Open the Dashboard in the default browser."""
        self._ensure_server_started()
        url = f"http://{self.host}:{self.port}"
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover - environment dependent
            print(f"agent-devtools: open {url} in your browser", file=sys.stderr)

    def start(self, *, open_browser: Optional[bool] = None) -> None:
        """Start the local debug server (if not already running) in a
        background thread. When ``open_browser`` is True (default when
        ``auto_open_browser`` is set), also opens the Dashboard UI."""
        self._ensure_server_started()
        should_open = self.auto_open_browser if open_browser is None else open_browser
        if should_open:
            # Open the browser only once per start (avoid re-opening on
            # every subsequent run/block close).
            if not getattr(self, "_browser_opened", False):
                self._browser_opened = True
                url = f"http://{self.host}:{self.port}"
                try:
                    webbrowser.open(url)
                except Exception:  # pragma: no cover
                    print(
                        f"agent-devtools: open {url} in your browser",
                        file=sys.stderr,
                    )

    def stop(self) -> None:
        """Stop the locally-started debug server, if any."""
        if self._server_thread is not None:
            # Uvicorn's Server has no public stop() on the thread; signal
            # by setting a flag is not supported through the public API.
            # For local dev, terminating the process stops the daemon thread.
            self._server_started = False