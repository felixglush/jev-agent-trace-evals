"""Commands that load and list traces."""

from __future__ import annotations

from pathlib import Path

import click

from s1evals.cli.root import cli, store_of


@cli.group()
def load() -> None:
    """Load traces into the store."""


@load.command("swechat")
@click.option("--n", default=20, show_default=True)
@click.option("--seed", default="s1evals-v1", show_default=True)
@click.option("--min-tool-calls", default=100, show_default=True)
@click.option("--min-prompts", default=3, show_default=True)
@click.option("--max-per-repo", default=3, show_default=True)
@click.option("--agent", default=None, help="Only sessions from this agent, e.g. 'Claude Code'.")
@click.pass_context
def load_swechat(ctx, n, seed, min_tool_calls, min_prompts, max_per_repo, agent) -> None:
    """Sample SWE-chat sessions (needs HF access to the gated dataset)."""
    from s1evals.loaders.swechat import SampleSpec, fetch_sample

    spec = SampleSpec(n, seed, min_tool_calls, min_prompts, max_per_repo, agent)
    store = store_of(ctx)
    for trace, events in fetch_sample(spec):
        store.put_trace(trace, events)
        click.echo(f"{trace.trace_id}  {trace.repo}  {trace.n_events} events  ~{trace.n_tokens} tokens")


@load.command("snapshot")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path), required=True)
@click.pass_context
def load_snapshot(ctx, paths) -> None:
    """Load common-schema JSON snapshots (fixtures)."""
    from s1evals.loaders import snapshot

    for p in paths:
        trace, events = snapshot.read(p)
        store_of(ctx).put_trace(trace, events)
        click.echo(f"{trace.trace_id}  {len(events)} events")


@cli.command("traces")
@click.pass_context
def list_traces(ctx) -> None:
    """List loaded traces."""
    for t in store_of(ctx).traces():
        click.echo(f"{t.trace_id}  {t.source}  {t.repo or '-'}  {t.n_events} events  ~{t.n_tokens} tokens")
