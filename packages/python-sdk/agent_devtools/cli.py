from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def _cmd_serve(args) -> None:
    if args.db:
        os.environ["AGENT_DEVTOOLS_DB"] = args.db
    from .store import default_db_path

    db_path = default_db_path()
    print(f"agent-devtools: tracing db -> {db_path}")
    print(f"agent-devtools: open http://{args.host}:{args.port} in your browser")
    import uvicorn

    uvicorn.run("agent_devtools.server.main:app", host=args.host, port=args.port, reload=False)


def _cmd_test(args) -> None:
    """Run fixture-based assertions for CI: agent-devtools test fixtures/*.json"""
    from .store import TraceStore

    paths = []
    for pattern in args.fixtures:
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        print("No fixtures matched.", file=sys.stderr)
        sys.exit(2)

    store = TraceStore(args.db or ":memory:")
    failures = 0
    for path in paths:
        with open(path) as f:
            fixture = json.load(f)
        run_id = store.import_fixture(fixture)
        events = store.get_events(run_id)
        run_failures = [e for e in events if e.type == "assertion.failed"]
        status = "PASS" if not run_failures else "FAIL"
        print(f"[{status}] {path} (run {run_id})")
        for e in run_failures:
            print(f"    - {e.payload.get('name')}: {e.payload.get('details')}")
            failures += 1
    if failures:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-devtools")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the local DevTools server + UI")
    serve.add_argument("--db", default=None, help="Path to the SQLite trace file")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=4173)
    serve.set_defaults(func=_cmd_serve)

    test = sub.add_parser("test", help="Replay fixtures and fail CI on assertion.failed events")
    test.add_argument("fixtures", nargs="+", help="Glob(s) for fixture JSON files")
    test.add_argument("--db", default=None)
    test.set_defaults(func=_cmd_test)

    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
