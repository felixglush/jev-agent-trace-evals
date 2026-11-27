"""`s1evals` command line. Each module registers one group of commands on `cli`."""

from s1evals.cli import data, trace  # noqa: F401  (registers commands)
from s1evals.cli.root import cli

__all__ = ["cli"]
