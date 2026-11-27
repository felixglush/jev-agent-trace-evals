"""Root `s1evals` command group and helpers shared by every command module."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click

from s1evals import rubrics as rubrics_mod
from s1evals.paths import REPO_ROOT
from s1evals.store import Store

DEFAULT_DB = Path(os.environ.get("S1EVALS_DB", REPO_ROOT / "data" / "s1evals.duckdb"))


def echo_json(obj) -> None:
    click.echo(json.dumps(obj, indent=1, ensure_ascii=False, default=str))


@click.group()
@click.option("--db", type=click.Path(path_type=Path), default=DEFAULT_DB, show_default=True)
@click.option("--rubrics-dir", type=click.Path(path_type=Path), default=rubrics_mod.DEFAULT_DIR, show_default=True)
@click.pass_context
def cli(ctx: click.Context, db: Path, rubrics_dir: Path) -> None:
    """System One evals on coding-agent traces."""
    ctx.obj = {"store": Store(db), "rubrics_dir": rubrics_dir}


def store_of(ctx: click.Context) -> Store:
    return ctx.obj["store"]


def rubrics_of(ctx: click.Context) -> dict[str, rubrics_mod.Rubric]:
    return rubrics_mod.load(ctx.obj["rubrics_dir"])
