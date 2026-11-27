import json

from click.testing import CliRunner
from conftest import FIXTURES

from s1evals.cli import cli


def invoke(db, *args, env=None):
    result = CliRunner().invoke(cli, ["--db", str(db), *args], env=env, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def test_load_and_trace_tools(tmp_path):
    db = tmp_path / "c.duckdb"
    invoke(db, "load", "snapshot", *map(str, sorted(FIXTURES.glob("*.json"))))
    assert "fx_retry" in invoke(db, "traces")
    hits = json.loads(invoke(db, "trace", "--trace-id", "fx_retry", "search", "multipart"))
    assert hits[0]["seq"] == 7


def test_trace_tools_read_snapshot_from_env(tmp_path):
    env = {"S1EVALS_SNAPSHOT": str(FIXTURES / "fx_cleanup.json")}
    ov = json.loads(invoke(tmp_path / "unused.duckdb", "trace", "overview", env=env))
    assert ov["trace_id"] == "fx_cleanup" and ov["user_message_seqs"] == [1, 12]
    pair = json.loads(invoke(tmp_path / "unused.duckdb", "trace", "tool-result", "13", env=env))
    assert "1 failed" in pair["paired"]["content"]
