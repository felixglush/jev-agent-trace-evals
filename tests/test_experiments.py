import pytest

from s1evals import experiments
from s1evals.domain import JudgeName, Verdict


def test_reusing_a_run_id_after_a_rubric_change_is_refused(store, rubrics):
    old = Verdict("fx_retry", "task_type", JudgeName.JEV, "feature", 0.9, "task_type@v0/jev:jev-1.14.0")
    store.put_scores("r1", [old])
    with pytest.raises(ValueError, match="use a new --run-id"):
        experiments._done(store, "r1", rubrics)


def test_public_problems_drop_messages(tmp_path):
    p = experiments.Problems(tmp_path / "p.jsonl")
    p.add(JudgeName.CLAUDE_AGENT, "t1", "JudgeError", "model said: <quoted trace text>", "task_type")
    assert p.public() == [{"judge": "claude_agent", "trace_id": "t1", "rubric_id": "task_type", "kind": "JudgeError"}]
    assert "quoted trace text" in (tmp_path / "p.jsonl").read_text()
