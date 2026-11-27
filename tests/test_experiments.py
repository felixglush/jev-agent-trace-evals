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


def test_log_reports_only_what_this_config_selected(store, rubrics, tmp_path):
    jv = rubrics["task_type"].judge_version(JudgeName.JEV, "jev-1.14.0")
    store.put_scores("r1", [
        Verdict("fx_retry", "task_type", JudgeName.JEV, "bugfix", 0.9, jv),
        Verdict("fx_retry", "task_type", JudgeName.CLAUDE_AGENT, "bugfix", 0.9, jv),
        Verdict("fx_cleanup", "task_type", JudgeName.JEV, "bugfix", 0.9, jv),
    ])  # fmt: skip
    cfg = experiments.RunConfig("r1", "", ["fx_retry"], ["task_type"], ["jev"])
    slice_map = experiments.extract_all(store, {"task_type": rubrics["task_type"]}, cfg.trace_ids)
    out = experiments.write_log(store, rubrics, cfg, slice_map, [], out_root=tmp_path)
    rows = (out / "verdicts.jsonl").read_text().splitlines()
    assert len(rows) == 1 and '"fx_retry"' in rows[0] and '"jev"' in rows[0]


def test_problems_fixed_by_a_resume_drop_out_of_the_log(store, rubrics, tmp_path):
    jv = rubrics["task_type"].judge_version(JudgeName.JEV, "jev-1.14.0")
    store.put_scores("r1", [Verdict("fx_retry", "task_type", JudgeName.JEV, "bugfix", 0.9, jv)])
    cfg = experiments.RunConfig("r1", "", ["fx_retry"], ["task_type"], ["jev"])
    slice_map = experiments.extract_all(store, {"task_type": rubrics["task_type"]}, cfg.trace_ids)
    problems = [
        {"judge": "jev", "trace_id": "fx_retry", "rubric_id": "task_type", "kind": "JudgeError"},  # retried, fixed
        {"judge": "jev", "trace_id": "fx_retry", "rubric_id": None, "kind": "JudgeError"},  # session later succeeded
        {"judge": "claude_agent", "trace_id": "fx_retry", "rubric_id": None, "kind": "JudgeError"},  # still failing
    ]
    out = experiments.write_log(store, rubrics, cfg, slice_map, problems, out_root=tmp_path)
    assert len((out / "problems.jsonl").read_text().splitlines()) == 1


def test_a_committed_log_imports_into_a_fresh_store(store, rubrics, tmp_path):
    jv = rubrics["task_type"].judge_version(JudgeName.JEV, "jev-1.14.0")
    store.put_scores(
        "r1", [Verdict("fx_retry", "task_type", JudgeName.JEV, "bugfix", 0.9, jv, {"bugfix": 0.9}, (1, 2))]
    )
    cfg = experiments.RunConfig("r1", "", ["fx_retry"], ["task_type"], ["jev"])
    slice_map = experiments.extract_all(store, {"task_type": rubrics["task_type"]}, cfg.trace_ids)
    out = experiments.write_log(store, rubrics, cfg, slice_map, [], out_root=tmp_path)

    from s1evals.store import Store

    fresh = Store(tmp_path / "fresh.duckdb")
    assert experiments.import_log(fresh, out) == ("r1", 1)
    [(_, v)] = fresh.scores(run_id="r1")
    assert v.label == "bugfix" and v.evidence_ref == (1, 2) and v.probabilities == {"bugfix": 0.9}
