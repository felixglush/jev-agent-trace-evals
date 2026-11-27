from pathlib import Path

import pytest

from s1evals import rubrics as rubrics_mod
from s1evals.loaders import snapshot
from s1evals.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def rubrics():
    return rubrics_mod.load()


@pytest.fixture
def retry_events():
    return snapshot.read(FIXTURES / "fx_retry.json")[1]


@pytest.fixture
def cleanup_events():
    return snapshot.read(FIXTURES / "fx_cleanup.json")[1]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.duckdb")
    for p in sorted(FIXTURES.glob("*.json")):
        s.put_trace(*snapshot.read(p))
    return s
