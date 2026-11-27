"""SWE-chat loader: sample sessions and map `conversations` rows to events.

The dataset is gated on Hugging Face, so reads go through `HfFileSystem`, which
picks up the token from `HF_TOKEN` or the local HF login. Parquet is read with
column projection and a session_id filter, so only the sampled rows travel.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from s1evals.domain import Event, Role, Trace, TurnType
from s1evals.text import estimate_tokens

REPO = "datasets/SALT-NLP/SWE-chat"
SOURCE = "swe-chat"

SESSION_COLUMNS = [
    "session_id",
    "repo_id",
    "agent",
    "model",
    "tool_call_count",
    "prompt_count",
    "output_tokens",
    "kind",
    "session_success",
]
CONVERSATION_COLUMNS = [
    "session_id",
    "turn_number",
    "role",
    "turn_type",
    "content",
    "tool_name",
    "tool_call_id",
    "command",
    "input_tokens",
    "output_tokens",
]

# conversations.turn_type -> (role, turn_type) in the common schema.
# Metadata rows (summaries, snapshots, progress, queue ops) carry no judgment-
# relevant content and are dropped.
TURN_MAP: dict[str, tuple[Role, TurnType]] = {
    "user_prompt": (Role.USER, TurnType.MESSAGE),
    "system_injected": (Role.SYSTEM, TurnType.MESSAGE),
    "assistant_response": (Role.ASSISTANT, TurnType.MESSAGE),
    "assistant_thinking": (Role.ASSISTANT, TurnType.THINKING),
    "tool_use": (Role.ASSISTANT, TurnType.TOOL_CALL),
    "tool_result": (Role.TOOL, TurnType.TOOL_RESULT),
}

_FAILURE = re.compile(
    r"<tool_use_error>|^\s*error\b|traceback \(most recent call last\)|exit code [1-9]\d*"
    r"|command not found|no such file or directory|permission denied|\bfailed\b",
    re.IGNORECASE | re.MULTILINE,
)


def looks_failed(content: str) -> bool:
    """Heuristic failure flag for tool results (the dataset has no is_error column)."""
    return bool(_FAILURE.search(content[:4000]))


@dataclass(frozen=True)
class SampleSpec:
    n: int = 20
    seed: str = "s1evals-v1"
    min_tool_calls: int = 100
    min_prompts: int = 3
    max_per_repo: int = 3
    agent: str | None = None


def select_sessions(rows: Iterable[Mapping], spec: SampleSpec) -> list[Mapping]:
    """Deterministic sample with the blog's filters: >=100 tool calls, >=3 user
    prompts, <=3 sessions per repo. Duplicated session ids keep the record
    with the most output tokens, as the dataset card recommends."""
    best: dict[str, Mapping] = {}
    for r in rows:
        if r["kind"]:
            continue
        if (r["tool_call_count"] or 0) < spec.min_tool_calls or (r["prompt_count"] or 0) < spec.min_prompts:
            continue
        if spec.agent and r["agent"] != spec.agent:
            continue
        prev = best.get(r["session_id"])
        if prev is None or (r["output_tokens"] or 0) > (prev["output_tokens"] or 0):
            best[r["session_id"]] = r

    def rank(r: Mapping) -> str:
        return hashlib.sha256(f"{spec.seed}:{r['session_id']}".encode()).hexdigest()

    per_repo: Counter[str] = Counter()
    chosen: list[Mapping] = []
    for r in sorted(best.values(), key=rank):
        if per_repo[r["repo_id"]] >= spec.max_per_repo:
            continue
        per_repo[r["repo_id"]] += 1
        chosen.append(r)
        if len(chosen) == spec.n:
            break
    return chosen


def map_rows(session: Mapping, rows: Iterable[Mapping]) -> tuple[Trace, list[Event]]:
    """Map one session's conversation rows (any order) to the common schema."""
    trace_id = session["session_id"]
    events: list[Event] = []
    for r in sorted(rows, key=lambda r: r["turn_number"]):
        mapped = TURN_MAP.get(r["turn_type"])
        if mapped is None:
            continue
        role, turn_type = mapped
        content = r["content"] or ""
        events.append(
            Event(
                trace_id=trace_id,
                seq=len(events) + 1,
                role=role,
                turn_type=turn_type,
                content=content,
                tokens=estimate_tokens(content),
                tool_name=r["tool_name"] or None,
                tool_call_id=r["tool_call_id"] or None,
                command=r["command"] or None,
                is_error=turn_type is TurnType.TOOL_RESULT and looks_failed(content),
            )
        )
    _attach_tool_names(events)
    trace = Trace(
        trace_id=trace_id,
        source=SOURCE,
        repo=session["repo_id"],
        agent=session["agent"],
        model=session["model"] or None,
        n_events=len(events),
        n_tokens=sum(e.tokens for e in events),
        outcome=str(session["session_success"]) if session.get("session_success") else None,
    )
    return trace, events


def _attach_tool_names(events: list[Event]) -> None:
    """Tool results inherit tool_name/command from their call via tool_call_id."""
    calls = {e.tool_call_id: e for e in events if e.turn_type is TurnType.TOOL_CALL and e.tool_call_id}
    for i, e in enumerate(events):
        call = calls.get(e.tool_call_id) if e.turn_type is TurnType.TOOL_RESULT else None
        if call and (e.tool_name is None or e.command is None):
            events[i] = replace(e, tool_name=e.tool_name or call.tool_name, command=e.command or call.command)


# --- Remote reads -------------------------------------------------------------


def _hf_parquet(name: str, columns: list[str], session_ids: list[str] | None = None) -> list[dict]:
    import pyarrow.dataset as ds
    from huggingface_hub import HfFileSystem

    fs = HfFileSystem()
    dataset = ds.dataset(f"{REPO}/{name}", filesystem=fs, format="parquet")
    filt = ds.field("session_id").isin(session_ids) if session_ids is not None else None
    return dataset.to_table(columns=columns, filter=filt).to_pylist()


def fetch_sample(spec: SampleSpec) -> list[tuple[Trace, list[Event]]]:
    sessions = select_sessions(_hf_parquet("sessions.parquet", SESSION_COLUMNS), spec)
    ids = [s["session_id"] for s in sessions]
    rows = _hf_parquet("conversations.parquet", CONVERSATION_COLUMNS, ids)
    by_session: dict[str, list[dict]] = {i: [] for i in ids}
    for r in rows:
        by_session[r["session_id"]].append(r)
    return [map_rows(s, by_session[s["session_id"]]) for s in sessions]
