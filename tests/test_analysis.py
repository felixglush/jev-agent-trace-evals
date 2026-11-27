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


def test_auroc_and_coverage_rank_right_answers_above_wrong_ones():
    from s1evals.analysis import auroc, confidence_quality

    assert auroc([(0.9, True), (0.2, False)]) == 1.0
    assert auroc([(0.5, True), (0.5, False)]) == 0.5
    assert auroc([(0.9, True)]) is None
    fast = {
        ("t1", "r"): Verdict("t1", "r", JudgeName.JEV, "yes", 0.95, "v"),
        ("t2", "r"): Verdict("t2", "r", JudgeName.JEV, "yes", 0.2, "v"),
    }
    q = confidence_quality(fast, {("t1", "r"): "yes", ("t2", "r"): "no"})
    assert q["auroc"] == 1.0
    kept_at_half = next(row for row in q["coverage"] if row["threshold"] == 0.5)
    assert kept_at_half == {"threshold": 0.5, "coverage": 0.5, "accuracy_kept": 1.0}


def test_roc_and_suggested_threshold():
    scored = [(0.9, True)] * 12 + [(0.6, True)] * 4 + [(0.6, False)] * 4 + [(0.2, False)] * 5
    points = analysis.roc(scored)
    assert points[0] == {"threshold": None, "tpr": 0.0, "fpr": 0.0}
    assert points[-1] == {"threshold": 0.2, "tpr": 1.0, "fpr": 1.0}
    assert analysis.auroc(scored) > 0.8
    assert analysis.suggest_threshold(scored, 0.95) == 0.9  # only the 12 confident answers are all right
    assert analysis.suggest_threshold(scored, 0.8) == 0.6  # 16/20 kept answers agree
    assert analysis.suggest_threshold(scored, 0.99, min_kept=13) is None


def test_tune_thresholds_reports_per_rubric_and_held_out():
    fast = {
        (f"t{i}", "r"): Verdict(f"t{i}", "r", JudgeName.JEV, "yes" if i < 16 else "no", 0.9 if i < 16 else 0.3, "v")
        for i in range(20)
    }
    reference = {(f"t{i}", "r"): "yes" for i in range(20)}
    out = analysis.tune_thresholds(fast, reference, 0.9, {"r": 0.5})
    r = out["by_rubric"]["r"]
    assert r["n"] == 20 and r["auroc"] == 1.0 and r["suggested"] == 0.9
    assert r["current_coverage"] == 0.8 and r["current_accuracy"] == 1.0
    assert r["held_out"] == {"coverage": 0.8, "accuracy_kept": 1.0}
