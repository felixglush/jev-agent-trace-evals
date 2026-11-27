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
