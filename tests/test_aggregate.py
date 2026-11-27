import pytest

from s1evals.judges.aggregate import any_unresolved, correction_severity


def test_any_unresolved_takes_the_worst_failure():
    label, probs, conf = any_unresolved([{"unresolved": 0.1}, {"unresolved": 0.8}])
    assert label == "yes" and probs["yes"] == 0.8 and conf == pytest.approx(0.6)


def test_many_small_probabilities_do_not_add_up_to_yes():
    label, _, conf = any_unresolved([{"unresolved": 0.2}] * 40)
    assert label == "no" and conf == pytest.approx(0.6)


@pytest.mark.parametrize(
    ("items", "label"),
    [
        ([{"corrects": 0.1, "redirects": 0.9}], "none"),  # redirect without a correction is not one
        ([{"corrects": 0.9, "redirects": 0.1}, {"corrects": 0.2, "redirects": 0.2}], "minor"),
        ([{"corrects": 0.9, "redirects": 0.1}, {"corrects": 0.7, "redirects": 0.8}], "major"),
    ],
)
def test_correction_severity_takes_the_most_severe_follow_up(items, label):
    got, probs, _ = correction_severity(items)
    assert got == label and sum(probs.values()) == pytest.approx(1.0)
