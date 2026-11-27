"""Judge probes, experiment runs and logs, and SQL over labels (evals as indexes)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import click

from s1evals import slices
from s1evals.cli.root import cli, echo_json, rubrics_of, store_of
from s1evals.experiments import ALL_JUDGES, RunConfig


@cli.group()
def experiment() -> None:
    """Run judges over traces and write experiment logs."""


@experiment.command("run")
@click.option("--run-id", default=None, help="Defaults to <UTC date>-<slug>.")
@click.option("--slug", default="swechat-sample")
@click.option("--description", default="")
@click.option("--judge", "judges", multiple=True, type=click.Choice([j.value for j in ALL_JUDGES]))
@click.option("--trace", "trace_ids", multiple=True, help="Default: all loaded traces.")
@click.option("--rubric", "rubric_ids", multiple=True, help="Default: every rubric.")
@click.option("--workers", default=4, show_default=True, help="Parallel Claude sessions.")
@click.pass_context
def experiment_run(ctx, run_id, slug, description, judges, trace_ids, rubric_ids, workers) -> None:
    """Run (or resume) an experiment and write experiments/<run_id>/."""
    from s1evals import experiments

    store, rs = store_of(ctx), rubrics_of(ctx)
    cfg = RunConfig(
        run_id=run_id or f"{datetime.now(UTC):%Y-%m-%d}-{slug}",
        description=description,
        trace_ids=list(trace_ids) or [t.trace_id for t in store.traces()],
        rubric_ids=list(rubric_ids) or sorted(rs),
        judges=list(judges) or [j.value for j in ALL_JUDGES],
        workers=workers,
    )
    out = experiments.run(store, rs, cfg, store.path.parent, log=lambda m: click.echo(m, err=True))
    click.echo(out / "REPORT.md")


@experiment.command("report")
@click.argument("run_id")
@click.pass_context
def experiment_report(ctx, run_id) -> None:
    """Recompute metrics and rewrite a run's log (e.g. after new human feedback)."""
    from s1evals import experiments

    out = experiments.EXPERIMENTS_DIR / run_id
    cfg = RunConfig(
        **{
            k: v
            for k, v in json.loads((out / "config.json").read_text()).items()
            if k in RunConfig.__dataclass_fields__
        }
    )
    rs = {rid: r for rid, r in rubrics_of(ctx).items() if rid in cfg.rubric_ids}
    store = store_of(ctx)
    slice_map = {}
    for tid in cfg.trace_ids:
        for r in rs.values():
            s = store.get_slice(tid, r.id, r.version)
            slice_map[(tid, r.id)] = s if s is not None else slices.extract(r, store.events(tid))
    problems = (
        [json.loads(line) for line in (out / "problems.jsonl").read_text().splitlines() if line.strip()]
        if (out / "problems.jsonl").exists()
        else []
    )
    click.echo(experiments.write_log(store, rs, cfg, slice_map, problems) / "REPORT.md")


@cli.command("query")
@click.argument("sql")
@click.option("--run-id", default=None, help="Run whose labels fill the trace_labels view (default: latest).")
@click.option("--include-unadmitted", is_flag=True, help="Also pivot rubrics that have not passed the gates.")
@click.pass_context
def query(ctx, sql, run_id, include_unadmitted) -> None:
    """Run read-only SQL. `trace_labels` pivots the routed label per rubric into columns (evals as indexes)."""
    from s1evals import index

    echo_json(index.query(store_of(ctx), rubrics_of(ctx), sql, run_id, include_unadmitted))
