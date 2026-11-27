"""Read-only trace query tools: the slow judge's only window into a trace.

These mirror the design doc's tool set: get_turns(role, range), search(text),
get_tool_result(id), plus an overview. Every function is pure over a list of
events so the CLI, the agent and tests share one implementation.
"""

from __future__ import annotations

from collections import Counter

from s1evals.domain import Event, Role, Trace, TurnType

DEFAULT_MAX_CHARS = 1500


def render(e: Event, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    content = (
        e.content if len(e.content) <= max_chars else e.content[:max_chars] + f" …[+{len(e.content) - max_chars} chars]"
    )
    row = {"seq": e.seq, "role": e.role.value, "turn_type": e.turn_type.value, "content": content}
    if e.tool_name:
        row["tool_name"] = e.tool_name
    if e.command:
        row["command"] = e.command
    if e.turn_type is TurnType.TOOL_RESULT:
        row["looks_failed"] = e.is_error
    return row


def overview(trace: Trace, events: list[Event]) -> dict:
    tools = Counter(e.tool_name for e in events if e.turn_type is TurnType.TOOL_CALL)
    return {
        "trace_id": trace.trace_id,
        "repo": trace.repo,
        "agent": trace.agent,
        "n_events": len(events),
        "approx_tokens": trace.n_tokens,
        "user_message_seqs": [e.seq for e in events if e.is_user_message],
        "assistant_message_count": sum(e.is_assistant_message for e in events),
        "tool_calls_by_name": dict(tools.most_common()),
        "failed_tool_result_seqs": [e.seq for e in events if e.turn_type is TurnType.TOOL_RESULT and e.is_error],
    }


def get_turns(
    events: list[Event],
    role: Role | None = None,
    turn_type: TurnType | None = None,
    start: int | None = None,
    end: int | None = None,
    limit: int = 50,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[dict]:
    """Events with seq in [start, end], optionally filtered by role/turn type."""
    picked = [
        e
        for e in events
        if (role is None or e.role is role)
        and (turn_type is None or e.turn_type is turn_type)
        and (start is None or e.seq >= start)
        and (end is None or e.seq <= end)
    ]
    return [render(e, max_chars) for e in picked[:limit]]


def search(events: list[Event], text: str, limit: int = 20, context_chars: int = 200) -> list[dict]:
    """Case-insensitive substring search; returns a window around each hit."""
    needle = text.lower()
    hits = []
    for e in events:
        i = e.content.lower().find(needle)
        if i < 0:
            continue
        lo, hi = max(0, i - context_chars), i + len(text) + context_chars
        hits.append({**render(e, 0), "content": e.content[lo:hi], "match_at": i})
        if len(hits) == limit:
            break
    return hits


def get_tool_result(events: list[Event], seq: int, max_chars: int = 6000) -> dict:
    """A tool call or result by seq, paired with its counterpart."""
    by_seq = {e.seq: e for e in events}
    if seq not in by_seq:
        raise KeyError(f"no event with seq {seq}")
    e = by_seq[seq]
    out = {"event": render(e, max_chars)}
    if e.tool_call_id:
        partner = next(
            (o for o in events if o.tool_call_id == e.tool_call_id and o.seq != e.seq),
            None,
        )
        if partner:
            out["paired"] = render(partner, max_chars)
    return out
