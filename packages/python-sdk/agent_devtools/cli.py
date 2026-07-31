"""CLI commands for agent-devtools."""

import json
import sys
import os
from pathlib import Path
from typing import Optional
import click

from .server import app as server_app
from .transport import Transport
from .test_runner import TestRunner
import uvicorn


@click.group()
def cli():
    """Agent DevTools CLI."""
    pass


@cli.command()
@click.option("--port", default=8787, help="Port to run the server on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
def serve(port: int, host: str):
    """Start the debug server."""
    click.echo(f"Starting Agent DevTools server on http://{host}:{port}")
    uvicorn.run(server_app, host=host, port=port)


@cli.command()
@click.argument("run_id")
@click.option("--output", "-o", help="Output file path (default: stdout)")
def export(run_id: str, output: Optional[str]):
    """Export a run as JSON fixture."""
    transport = Transport()
    try:
        data = transport.export_run(run_id)
        json_str = json.dumps(data, indent=2, default=str)
        if output:
            Path(output).write_text(json_str)
            click.echo(f"Exported run {run_id} to {output}")
        else:
            click.echo(json_str)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def list():
    """List all runs."""
    transport = Transport()
    runs = transport.list_runs(limit=100)
    if not runs:
        click.echo("No runs found.")
        return
    click.echo(f"{'ID':<36} {'Project':<20} {'Status':<12} {'Created'}")
    click.echo("-" * 80)
    for r in runs:
        click.echo(f"{r['id']:<36} {r['project_name']:<20} {r['status']:<12} {r['created_at']}")


@cli.command()
@click.argument("path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--json", "-j", "json_output", is_flag=True, help="Output as JSON")
def test(path: str, verbose: bool, json_output: bool):
    """Run tests from a file, directory, or glob pattern."""
    runner = TestRunner()
    results = runner.run(path)

    if json_output:
        output = {
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r.passed),
                "failed": sum(1 for r in results if not r.passed)
            },
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "assertions": [
                        {"name": a.name, "passed": a.passed, "message": a.message}
                        for a in r.assertions
                    ]
                }
                for r in results
            ]
        }
        click.echo(json.dumps(output, indent=2))
    else:
        for r in results:
            status = "✅" if r.passed else "❌"
            click.echo(f"{status} {r.name}")
            if verbose or not r.passed:
                for a in r.assertions:
                    if not a.passed:
                        click.echo(f"  ❌ {a.name}: {a.message}")
                    elif verbose:
                        click.echo(f"  ✅ {a.name}")
                if r.message and not r.passed:
                    click.echo(f"  {r.message}")

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        click.echo(f"\nSummary: {passed} passed, {failed} failed, {total} total")
        sys.exit(1 if failed > 0 else 0)