from datetime import datetime

from conftest import FIXTURES

from s1evals.domain import Decided, Evidence, JudgeName, Missing, Verdict
from s1evals.loaders import snapshot
from s1evals.store import Feedback


def test_reload_is_idempotent(store):
    trace, events = snapshot.read(FIXTURES / "fx_retry.json")
    store.put_trace(trace, events)
    assert len(store.events("fx_retry")) == len(events)
    assert [t.trace_id for t in store.traces()] == ["fx_cleanup", "fx_retry"]


def test_slices_round_trip(store):
    for result in (Evidence({"a": [1]}, (1, 2), 5, target=2), Decided("n/a", "none"), Missing("why")):
        store.put_slice("fx_retry", "r", 1, result)
        assert store.get_slice("fx_retry", "r", 1) == result


def test_reloading_a_trace_drops_its_cached_slices(store):
    store.put_slice("fx_retry", "r", 1, Missing("old"))
    store.put_slice("fx_cleanup", "r", 1, Missing("kept"))
    store.put_trace(*snapshot.read(FIXTURES / "fx_retry.json"))
    assert store.get_slice("fx_retry", "r", 1) is None
    assert store.get_slice("fx_cleanup", "r", 1) == Missing("kept")


def test_scores_keep_both_judges_per_pair(store):
    v = Verdict("fx_retry", "task_type", JudgeName.JEV, "feature", 0.9, "v1", {"feature": 0.9}, (1,))
    store.put_scores("run", [v, Verdict("fx_retry", "task_type", JudgeName.CLAUDE_AGENT, "feature", 0.8, "v1")])
    assert {s[1].judge for s in store.scores(run_id="run")} == {JudgeName.JEV, JudgeName.CLAUDE_AGENT}
    assert store.scores(run_id="run")[1][1].probabilities == {"feature": 0.9}


def test_feedback_upserts_per_author(store):
    fb = Feedback("fx_retry", "user_correction", "major", "clear revert", "felix", datetime(2026, 1, 1))
    store.put_feedback(fb)
    store.put_feedback(Feedback("fx_retry", "user_correction", "minor", "changed mind", "felix", datetime(2026, 1, 2)))
    rows = store.feedback("fx_retry")
    assert len(rows) == 1 and rows[0].human_label == "minor"


def test_threads_mixing_reads_and_writes_do_not_conflict(store):
    from concurrent.futures import ThreadPoolExecutor

    v = Verdict("fx_retry", "task_type", JudgeName.JEV, "feature", 0.9, "v1")
    with ThreadPoolExecutor(8) as pool:
        futures = [pool.submit(store.events, "fx_retry") for _ in range(20)]
        futures += [pool.submit(store.put_scores, f"r{i}", [v]) for i in range(20)]
        for f in futures:
            f.result()
    assert len(store.run_ids()) == 20


def test_waits_for_another_process_holding_the_file(store):
    import subprocess
    import sys
    import time

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import duckdb,time; c=duckdb.connect({str(store.path)!r}); print('held', flush=True); time.sleep(1.5)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout.readline().strip() == "held"
    start = time.monotonic()
    assert store.traces()  # blocks until the other process lets go, then succeeds
    assert time.monotonic() - start > 0.5
    holder.wait()


def test_reading_a_fresh_path_creates_an_empty_store(tmp_path):
    from s1evals.store import Store

    assert Store(tmp_path / "new" / "db.duckdb").traces() == []
