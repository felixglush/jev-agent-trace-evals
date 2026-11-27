import os

import httpx
import pytest

from s1evals.domain import Evidence
from s1evals.judges import JudgeError
from s1evals.judges.jev import JevJudge, build_request, parse_response

EV = Evidence({"follow_ups": ["No, revert that"]}, (3, 4), 20)


def test_choice_request_sends_labels_as_criteria(rubrics):
    req = build_request(rubrics["task_type"], EV)
    q = req["questions"]["verdict"]
    assert q["type"] == "choice" and set(q["criteria"]) == set(rubrics["task_type"].labels)
    assert req["state"] == EV.state


ITEMS = Evidence(
    {
        "first_request": "Add a login page",
        "follow_ups": [{"user_follow_up": "thanks"}, {"user_follow_up": "No, revert"}],
    },
    (3, 4),
    30,
)


def test_item_rubric_asks_each_question_about_each_item_in_one_request(rubrics):
    req = build_request(rubrics["user_correction"], ITEMS)
    assert set(req["questions"]) == {"corrects_0", "redirects_0", "corrects_1", "redirects_1"}
    assert "No, revert" in req["questions"]["corrects_1"]["instructions"]
    assert req["state"] == {"first_request": "Add a login page"}  # the list itself is not shared state


def test_item_answers_are_aggregated_in_code(rubrics):
    noul = lambda p: {"type": "noul", "noul": p}  # noqa: E731
    answers = {"corrects_0": noul(0.1), "redirects_0": noul(0.1), "corrects_1": noul(0.9), "redirects_1": noul(0.8)}
    v = parse_response(rubrics["user_correction"], "t", ITEMS, {"answers": answers}, 0.1)
    assert v.label == "major" and v.confidence == pytest.approx(2 / 3)


def test_noul_request_maps_yes_no_to_true_false(rubrics):
    q = build_request(rubrics["user_frustration"], EV)["questions"]["verdict"]
    assert q["type"] == "noul" and set(q["criteria"]) == {"true", "false"}


def test_noul_answer_becomes_label_with_distance_confidence(rubrics):
    body = {
        "model": "jev-1.14.0",
        "answers": {"verdict": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 100},
    }
    v = parse_response(rubrics["user_frustration"], "t", EV, body, 0.1)
    assert v.label == "yes" and v.confidence == pytest.approx(0.8)
    assert v.cost_usd == pytest.approx(100 * 0.042e-6)
    assert v.evidence_ref == (3, 4)


def test_unknown_label_is_an_error_not_an_answer(rubrics):
    body = {"answers": {"verdict": {"choice": "huge", "confidence": 1, "probabilities": {"huge": 1}}}}
    with pytest.raises(JudgeError):
        parse_response(rubrics["task_type"], "t", EV, body, 0.1)


def test_client_error_raises_without_retry_storm(rubrics):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"detail": "bad"})

    judge = JevJudge(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(JudgeError, match="400"):
        judge.judge(rubrics["task_type"], "t", EV)
    assert len(calls) == 1


@pytest.mark.skipif(not os.environ.get("S1EVALS_LIVE"), reason="set S1EVALS_LIVE=1 to call the real Jev API")
def test_live_jev_reads_design_doc_example_as_major(rubrics, retry_events):
    from s1evals import slices

    ev = slices.extract(rubrics["user_correction"], retry_events)
    verdict, _ = JevJudge().judge(rubrics["user_correction"], "fx_retry", ev)
    assert verdict.label == "major"
