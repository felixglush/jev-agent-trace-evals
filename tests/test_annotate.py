from fastapi.testclient import TestClient

from s1evals import rubrics as rubrics_mod
from s1evals.annotate.app import create_app
from s1evals.domain import JudgeName, Verdict


def client(store):
    store.put_scores("run1", [
        Verdict("fx_retry", "user_correction", JudgeName.JEV, "major", 0.97, "v", {"major": 0.97, "minor": 0.03}, (6, 7)),
        Verdict("fx_retry", "user_correction", JudgeName.CLAUDE_AGENT, "major", 0.9, "v", explanation="reverted"),
    ])  # fmt: skip
    return TestClient(create_app(store, rubrics_mod.DEFAULT_DIR, "felix"))


def test_trace_view_shows_both_judges_slice_and_route(store):
    c = client(store)
    body = c.get("/api/traces/fx_retry").json()
    rc = next(r for r in body["rubrics"] if r["id"] == "user_correction")
    assert set(rc["verdicts"]) == {"jev", "claude_agent"}
    assert rc["verdicts"]["claude_agent"]["explanation"] == "reverted"
    assert rc["slice"]["kind"] == "evidence" and 7 in rc["slice"]["refs"]
    assert rc["route"] == {"route": "fast", "label": "major", "reason": "confidence 0.97"}
    assert len(body["events"]) == 15 and body["run_id"] == "run1"


def test_feedback_round_trips_and_marks_trace(store):
    c = client(store)
    assert c.post("/api/feedback", json={"trace_id": "fx_retry", "rubric_id": "user_correction",
                                         "human_label": "major", "comment": "clear revert"}).status_code == 200  # fmt: skip
    c.post("/api/feedback", json={"trace_id": "fx_retry", "rubric_id": "_trace", "comment": "good example"})
    body = c.get("/api/traces/fx_retry").json()
    rc = next(r for r in body["rubrics"] if r["id"] == "user_correction")
    assert rc["feedback"] == {"human_label": "major", "comment": "clear revert"}
    assert body["note"] == "good example"
    listed = {t["trace_id"]: t for t in c.get("/api/traces").json()}
    assert listed["fx_retry"]["labelled"] == 1 and listed["fx_retry"]["has_note"]


def test_feedback_rejects_unknown_label(store):
    r = client(store).post(
        "/api/feedback", json={"trace_id": "fx_retry", "rubric_id": "user_correction", "human_label": "huge"}
    )
    assert r.status_code == 400


def test_page_is_served(store):
    assert "Trace Annotator" in client(store).get("/").text


def test_review_lists_each_jev_answer_against_the_agent(store):
    store.put_scores("r9", [
        Verdict("fx_retry", "task_type", JudgeName.JEV, "question", 0.95, "v"),
        Verdict("fx_retry", "task_type", JudgeName.CLAUDE_AGENT, "bugfix", 0.9, "v"),
        Verdict("fx_retry", "task_type", JudgeName.CLAUDE_SLICE, "bugfix", 0.9, "v"),
    ])  # fmt: skip
    rows = client(store).get("/api/review", params={"run_id": "r9"}).json()["rows"]
    assert rows == [{
        "trace_id": "fx_retry", "rubric_id": "task_type", "jev": "question", "confidence": 0.95, "probabilities": {},
        "agent": "bugfix", "claude_slice": "bugfix", "human": None, "agrees": False, "kept": True,
    }]  # fmt: skip
