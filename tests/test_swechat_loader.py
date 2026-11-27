from s1evals.domain import Role, TurnType
from s1evals.loaders.swechat import SampleSpec, map_rows, select_sessions


def session(sid, repo="o/r", tools=150, prompts=4, out=10, kind=""):
    return {"session_id": sid, "repo_id": repo, "agent": "Claude Code", "model": "m", "tool_call_count": tools,
            "prompt_count": prompts, "output_tokens": out, "kind": kind, "session_success": "80"}  # fmt: skip


def test_sample_applies_blog_filters_and_repo_cap():
    rows = [session(f"s{i}", repo="same") for i in range(5)] + [
        session("few_tools", tools=10), session("few_prompts", prompts=2), session("review", kind="agent_review"),
        session("other", repo="o/other"),
    ]  # fmt: skip
    picked = [r["session_id"] for r in select_sessions(rows, SampleSpec(n=10))]
    assert "other" in picked
    assert not {"few_tools", "few_prompts", "review"} & set(picked)
    assert sum(p.startswith("s") for p in picked) == 3


def test_sample_is_deterministic_and_dedups_by_output_tokens():
    rows = [session("a", out=1), session("a", out=99, repo="o/x"), session("b")]
    first = select_sessions(rows, SampleSpec(n=2))
    assert first == select_sessions(list(reversed(rows)), SampleSpec(n=2))
    assert next(r for r in first if r["session_id"] == "a")["output_tokens"] == 99


def test_map_rows_orders_drops_metadata_and_links_tool_results():
    rows = [
        {"turn_number": 3, "turn_type": "tool_result", "content": "Exit code 1", "tool_name": None, "tool_call_id": "t1", "command": None},
        {"turn_number": 1, "turn_type": "user_prompt", "content": "fix it", "tool_name": None, "tool_call_id": None, "command": None},
        {"turn_number": 0, "turn_type": "file_snapshot", "content": "{}", "tool_name": None, "tool_call_id": None, "command": None},
        {"turn_number": 2, "turn_type": "tool_use", "content": "{}", "tool_name": "Bash", "tool_call_id": "t1", "command": "make"},
    ]  # fmt: skip
    trace, events = map_rows(session("s"), rows)
    assert [(e.seq, e.role, e.turn_type) for e in events] == [
        (1, Role.USER, TurnType.MESSAGE), (2, Role.ASSISTANT, TurnType.TOOL_CALL), (3, Role.TOOL, TurnType.TOOL_RESULT),
    ]  # fmt: skip
    assert events[2].tool_name == "Bash" and events[2].command == "make" and events[2].is_error
    assert trace.n_events == 3 and trace.repo == "o/r"
