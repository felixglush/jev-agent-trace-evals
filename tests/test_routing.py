from dataclasses import replace

import pytest

from s1evals.domain import Decided, Evidence, JudgeName, Missing, Verdict
from s1evals.routing import Route, resolve, route

EV = Evidence({"x": 1}, (1,), 10)


def fast(conf):
    return Verdict("t", "user_correction", JudgeName.JEV, "major", conf, "v")


@pytest.fixture
def rubric(rubrics):
    return replace(rubrics["user_correction"], admitted=True)


@pytest.mark.parametrize(
    ("slice_result", "verdict", "error", "expected"),
    [
        (Decided("none", "r"), None, None, Route.CODE),
        (Missing("r"), None, None, Route.MISSING),
        (Evidence({}, (), 99_999), None, None, Route.OVER_BUDGET),
        (EV, None, "boom", Route.FAST_ERROR),
        (EV, fast(0.49), None, Route.LOW_CONFIDENCE),
        (EV, fast(0.5), None, Route.FAST),
    ],
)
def test_truth_table(rubric, slice_result, verdict, error, expected):
    assert route(rubric, slice_result, verdict, error).route is expected


def test_unadmitted_rubric_goes_slow(rubrics):
    assert route(rubrics["user_correction"], EV, fast(0.99)).route is Route.NOT_ADMITTED


def test_fallback_takes_slow_label(rubric):
    slow = Verdict("t", "user_correction", JudgeName.CLAUDE_AGENT, "minor", 0.9, "v")
    d = resolve(route(rubric, EV, fast(0.1)), slow)
    assert (d.route, d.label, d.judge) == (Route.LOW_CONFIDENCE, "minor", JudgeName.CLAUDE_AGENT)


def test_fast_label_is_kept(rubric):
    slow = Verdict("t", "user_correction", JudgeName.CLAUDE_AGENT, "minor", 0.9, "v")
    assert resolve(route(rubric, EV, fast(0.9)), slow).label == "major"
