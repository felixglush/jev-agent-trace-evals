"""Commands over the rubrics folder and evidence slices."""

from __future__ import annotations

import click

from s1evals import slices
from s1evals.cli.root import cli, echo_json, rubrics_of, store_of
from s1evals.domain import Evidence


@cli.group()
def rubrics() -> None:
    """Inspect the rubrics folder."""


@rubrics.command("check")
@click.pass_context
def rubrics_check(ctx) -> None:
    """Validate every rubric file and its extractor."""
    rs = rubrics_of(ctx)
    for r in rs.values():
        click.echo(
            f"ok  {r.id} v{r.version}  {r.kind.value}/{r.scope.value}  labels={r.all_labels}  admitted={r.admitted}"
        )
    click.echo(f"{len(rs)} rubrics valid")


@cli.command("slice")
@click.argument("trace_id")
@click.argument("rubric_id")
@click.pass_context
def show_slice(ctx, trace_id, rubric_id) -> None:
    """Show the evidence slice a rubric extracts from a trace."""
    rubric = rubrics_of(ctx)[rubric_id]
    result = slices.extract(rubric, store_of(ctx).events(trace_id))
    payload = {"kind": type(result).__name__, **result.__dict__}
    if isinstance(result, Evidence):
        payload["over_budget"] = slices.over_budget(rubric, result)
    echo_json(payload)
