"""The annotation app and feedback export."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from s1evals.cli.root import cli, store_of


@cli.command("annotate")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True)
@click.option("--author", default=os.environ.get("USER", "annotator"), show_default=True)
@click.pass_context
def annotate(ctx, host, port, author) -> None:
    """Serve the annotation app: traces, rubric verdicts from both judges, and feedback."""
    import uvicorn

    from s1evals.annotate.app import create_app

    app = create_app(store_of(ctx), ctx.obj["rubrics_dir"], author)
    click.echo(f"annotation app on http://{host}:{port}", err=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command("feedback-export")
@click.argument("path", type=click.Path(path_type=Path))
@click.pass_context
def feedback_export(ctx, path: Path) -> None:
    """Write human feedback (labels and comments, no trace text) to a JSONL file."""
    rows = store_of(ctx).feedback()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for fb in rows:
            f.write(json.dumps({**fb.__dict__, "updated_at": fb.updated_at.isoformat()}) + "\n")
    click.echo(f"{len(rows)} feedback rows -> {path}")
