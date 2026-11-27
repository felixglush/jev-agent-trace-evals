from s1evals import analysis
from s1evals.domain import Decided, Evidence, JudgeName, Verdict
from s1evals.routing import Route


def v(trace, judge, label, conf=0.9, rubric="user_correction"):
    return Verdict(trace, rubric, judge, label, conf, "v", cost_usd=0.001)


def test_pipelines_routing_and_agreement(rubrics):
    rs = {"user_correction": rubrics["user_correction"]}
    slices = {("a", "user_correction"): Evidence({}, (), 10), ("b", "user_correction"): Evidence({}, (), 10),
              ("c", "user_correction"): Decided("none", "one message")}  # fmt: skip
    verdicts = [
        v("a", JudgeName.JEV, "major"), v("a", JudgeName.CLAUDE_AGENT, "major"),
        v("b", JudgeName.JEV, "none", conf=0.2), v("b", JudgeName.CLAUDE_AGENT, "minor"),
        v("c", JudgeName.CLAUDE_AGENT, "none"),
    ]  # fmt: skip
    m = analysis.compute(rs, slices, verdicts, human={("b", "user_correction"): "minor"})
    assert m.agreement_vs_agent[analysis.FAST_PIPELINE]["_all"].rate == 2 / 3
    assert m.labels[analysis.ROUTED][("b", "user_correction")] == "minor"  # low confidence fell back
    assert m.routes == {Route.FAST: 1, Route.LOW_CONFIDENCE: 1, Route.CODE: 1}
    assert m.agreement_vs_human[analysis.FAST_PIPELINE]["_all"].rate == 0.0
    assert m.cost["jev"]["usd_per_1000"] == 1.0


def test_confident_errors_and_calibration(rubrics):
    fast = {("a", "r"): v("a", JudgeName.JEV, "x", 0.95), ("b", "r"): v("b", JudgeName.JEV, "y", 0.3)}
    ref = {("a", "r"): "y", ("b", "r"): "y"}
    assert [e["trace_id"] for e in analysis.confident_errors(fast, ref)] == ["a"]
    cal = {row["bucket"]: row for row in analysis.calibration(fast, ref)}
    assert cal["[0.0, 0.5)"]["accuracy"] == 1.0 and cal["[0.9, 1.0]"]["accuracy"] == 0.0


def test_sufficiency_needs_95_percent_on_at_least_ten_pairs(rubrics):
    from s1evals.domain import Missing

    rs = {"task_type": rubrics["task_type"]}
    few = {(f"t{i}", "task_type"): Evidence({}, (), 5) for i in range(3)}
    agent = {k: "bugfix" for k in few}
    assert not analysis.gate1(rs, few, dict(agent), agent)["task_type"]["sufficient"]  # 3/3 but n < 10

    many = {(f"t{i}", "task_type"): Evidence({}, (), 5) for i in range(20)}
    many[("t0", "task_type")] = Missing("no user message")
    agent = {k: "bugfix" for k in many}
    labels = {k: "bugfix" for k in many if k != ("t0", "task_type")}
    g = analysis.gate1(rs, many, labels, agent)["task_type"]
    assert g["sufficiency"] == "19/20" and g["sufficient"]  # the Missing slice counts as the one miss
    labels.pop(("t1", "task_type"))
    assert not analysis.gate1(rs, many, labels, agent)["task_type"]["sufficient"]


def test_fast_path_agreement_excludes_fallbacks(rubrics):
    rs = {"user_correction": rubrics["user_correction"]}
    slices = {("a", "user_correction"): Evidence({}, (), 10), ("b", "user_correction"): Evidence({}, (), 10)}
    verdicts = [
        v("a", JudgeName.JEV, "major"), v("a", JudgeName.CLAUDE_AGENT, "minor"),
        v("b", JudgeName.JEV, "none", conf=0.1), v("b", JudgeName.CLAUDE_AGENT, "minor"),
    ]  # fmt: skip
    m = analysis.compute(rs, slices, verdicts)
    assert m.agreement_vs_agent[analysis.ROUTED]["_all"].rate == 0.5
    assert m.agreement_vs_agent[analysis.FAST_PATH]["_all"].total == 1
    assert m.agreement_vs_agent[analysis.FAST_PATH]["_all"].rate == 0.0
