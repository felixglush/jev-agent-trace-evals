"""Read-only trace queries: the slow judge's window into one trace, also handy for humans."""

from __future__ import annotations

import os
from pathlib import Path

import click

from s1evals import tracetools
from s1evals.cli.root import cli, echo_json, store_of
from s1evals.domain import Role, TurnType


def _trace_events(ctx: click.Context, trace_id: str | None):
    snap = os.environ.get("S1EVALS_SNAPSHOT")
    if snap:
        from s1evals.loaders import snapshot

        return snapshot.read(Path(snap))
    if not trace_id:
        raise click.UsageError("pass --trace-id or set S1EVALS_SNAPSHOT")
    store = store_of(ctx)
    return store.trace(trace_id), store.events(trace_id)


@cli.group()
@click.option("--trace-id", default=None, help="Trace to read (ignored when S1EVALS_SNAPSHOT is set).")
@click.pass_context
def trace(ctx, trace_id) -> None:
    """Read-only trace queries."""
    ctx.obj["trace_id"] = trace_id


@trace.command("overview")
@click.pass_context
def trace_overview(ctx) -> None:
    echo_json(tracetools.overview(*_trace_events(ctx, ctx.obj["trace_id"])))


@trace.command("turns")
@click.option("--role", type=click.Choice([r.value for r in Role]))
@click.option("--type", "turn_type", type=click.Choice([t.value for t in TurnType]))
@click.option("--start", type=int)
@click.option("--end", type=int)
@click.option("--limit", default=50, show_default=True)
@click.option("--max-chars", default=tracetools.DEFAULT_MAX_CHARS, show_default=True)
@click.pass_context
def trace_turns(ctx, role, turn_type, start, end, limit, max_chars) -> None:
    _, events = _trace_events(ctx, ctx.obj["trace_id"])
    echo_json(tracetools.get_turns(events, Role(role) if role else None, TurnType(turn_type) if turn_type else None,
                                   start, end, limit, max_chars))  # fmt: skip


@trace.command("search")
@click.argument("text")
@click.option("--limit", default=20, show_default=True)
@click.pass_context
def trace_search(ctx, text, limit) -> None:
    _, events = _trace_events(ctx, ctx.obj["trace_id"])
    echo_json(tracetools.search(events, text, limit))


@trace.command("tool-result")
@click.argument("seq", type=int)
@click.pass_context
def trace_tool_result(ctx, seq) -> None:
    _, events = _trace_events(ctx, ctx.obj["trace_id"])
    try:
        echo_json(tracetools.get_tool_result(events, seq))
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
