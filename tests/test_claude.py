from s1evals.domain import Evidence, JudgeName
from s1evals.judges.claude import ClaudeRun, agent_prompt, slice_prompt, to_verdicts


def run(verdicts, cost=1.2):
    return ClaudeRun({"verdicts": verdicts}, cost, 30.0, {})


def test_agent_prompt_names_tools_and_item_target(rubrics):
    p = agent_prompt("t1", [(rubrics["command_purpose"], 15), (rubrics["task_type"], None)])
    assert "s1evals trace overview" in p and "seq 15" in p
    assert "n/a" in p  # the agent may assign code-only labels


def test_slice_prompt_hides_code_only_labels(rubrics):
    p = slice_prompt([(rubrics["destructive_without_confirmation"], Evidence({"a": 1}, (1,), 3))])
    assert "n/a" not in p


def test_invalid_and_missing_verdicts_are_reported(rubrics):
    rs = [rubrics["task_type"], rubrics["user_correction"], rubrics["user_frustration"]]
    vs, problems = to_verdicts(
        run([
            {"rubric_id": "task_type", "label": "bugfix", "confidence": 0.9, "explanation": "e", "evidence_seqs": [1]},
            {"rubric_id": "user_correction", "label": "catastrophic", "confidence": 0.9, "explanation": "e"},
        ]),
        "t1", rs, JudgeName.CLAUDE_AGENT,
    )  # fmt: skip
    assert [v.rubric_id for v in vs] == ["task_type"]
    assert vs[0].evidence_ref == (1,) and abs(vs[0].cost_usd - 0.4) < 1e-9
    assert ("user_correction", "label 'catastrophic' not in ['none', 'minor', 'major']") in problems
    assert ("user_frustration", "no verdict returned") in problems
