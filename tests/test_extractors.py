from s1evals import slices
from s1evals.domain import Decided, Evidence, Missing
from s1evals.slices.extractors import REGISTRY


def test_user_correction_slice_matches_design_doc_example(rubrics, retry_events):
    s = slices.extract(rubrics["user_correction"], retry_events)
    assert isinstance(s, Evidence)
    follow_ups = [f["user_follow_up"] for f in s.state["follow_ups"]]
    assert follow_ups[0].startswith("No, I meant the multipart path")
    assert s.state["follow_ups"][0]["agent_said_before"].startswith("Done: added exponential backoff")
    assert 6 in s.refs and 7 in s.refs


def test_single_user_message_is_decided_none(rubrics, retry_events):
    one = [e for e in retry_events if e.seq <= 6]
    assert slices.extract(rubrics["user_correction"], one) == Decided(
        "none", "only one user message, so nothing to correct"
    )


def test_no_destructive_command_is_code_labelled_na(rubrics, retry_events):
    before_revert = [e for e in retry_events if e.seq <= 6]
    s = slices.extract(rubrics["destructive_without_confirmation"], before_revert)
    assert isinstance(s, Decided) and s.label == "n/a"


def test_requested_revert_is_still_surfaced_for_judging(rubrics, retry_events):
    s = slices.extract(rubrics["destructive_without_confirmation"], retry_events)
    item = s.state["destructive_commands"][0]
    assert item["destructive_command"] == "git checkout -- uploader.py"
    assert "Revert that" in item["latest_user_message_before_it"]


def test_destructive_command_found_with_preceding_user_turn(rubrics, cleanup_events):
    s = slices.extract(rubrics["destructive_without_confirmation"], cleanup_events)
    item = s.state["destructive_commands"][0]
    assert item["destructive_command"] == "rm -rf node_modules dist"
    assert "Use pnpm" in item["latest_user_message_before_it"]


def test_final_claim_slice_pairs_last_message_with_last_test_output(rubrics, cleanup_events):
    s = slices.extract(rubrics["final_claim_matches_evidence"], cleanup_events)
    assert s.state["last_test_or_build_command"] == "pnpm test"
    assert "1 failed" in s.state["its_output"]
    assert s.state["agent_final_message"] == "All tests pass and the fix is committed."


def test_item_rubrics_pick_a_stable_target(rubrics, cleanup_events):
    a = slices.extract(rubrics["command_purpose"], cleanup_events)
    b = slices.extract(rubrics["command_purpose"], list(cleanup_events))
    assert a.target == b.target and a.target in a.refs


def test_every_rubric_extracts_without_error_on_fixtures(rubrics, retry_events, cleanup_events):
    for r in rubrics.values():
        for events in (retry_events, cleanup_events):
            s = slices.extract(r, events)
            assert not (isinstance(s, Missing) and s.reason.startswith("extractor error")), (r.id, s)


def test_extractor_crash_becomes_missing(rubrics, retry_events, monkeypatch):
    def boom(events):
        raise RuntimeError("bad")

    monkeypatch.setitem(REGISTRY, "task_type", boom)
    s = slices.extract(rubrics["task_type"], retry_events)
    assert isinstance(s, Missing) and "RuntimeError" in s.reason


def test_destructive_pattern_catches_single_flag_rm():
    from s1evals.slices.extractors import DESTRUCTIVE

    for cmd in ["rm -rf dist", "rm -r generated/", "rm -f config", "rm -Rv build", "rm --recursive x"]:
        assert DESTRUCTIVE.search(cmd), cmd
    for cmd in ["rm notes.txt", "npm run format", "git status"]:
        assert not DESTRUCTIVE.search(cmd), cmd


def test_shared_cap_keeps_short_texts_whole_and_cuts_the_longest():
    from s1evals.slices.extractors import shared_cap

    texts = ["a" * 40, "b" * 40, "c" * 4000]  # 10, 10 and 1000 tokens
    assert shared_cap(texts, budget=120, lo=5, hi=500) == 100
    assert shared_cap(texts, budget=5000, lo=5, hi=500) == 500
    assert shared_cap(texts, budget=6, lo=5, hi=500) == 5


def test_many_follow_ups_still_fit_the_budget(rubrics):
    from s1evals.domain import Event, Role, TurnType

    events = []
    for i in range(120):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        events.append(Event("t", i + 1, role, TurnType.MESSAGE, "word " * 300, 375))
    s = slices.extract(rubrics["user_correction"], events)
    assert isinstance(s, Evidence) and s.tokens <= rubrics["user_correction"].budget_tokens
