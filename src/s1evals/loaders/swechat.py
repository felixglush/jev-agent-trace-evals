"""SWE-chat loader: sample sessions and map `conversations` rows to events.

The dataset is gated on Hugging Face, so reads go through `HfFileSystem`, which
picks up the token from `HF_TOKEN` or the local HF login.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from s1evals.domain import SHELL_TOOLS, Event, Role, Trace, TurnType
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

# Failure signals any tool can return: the harness's error wrapper or an error
# reply in place of a result. Only checked at the start, so file text that
# merely contains "Error:" or a traceback is not a failure.
_TOOL_ERROR = re.compile(r"\A\s*(?:<tool_use_error>|error\b)", re.IGNORECASE)
# Extra signals only a shell's output carries. A file read or search returns
# code and logs, where words like "error" or "failed" are content, not failure.
_SHELL_FAILURE = re.compile(
    r"<tool_use_error>|(?:exit code|exited with code|exit status)\W{0,3}[1-9]\d*"
    r"|command not found|no such file or directory|permission denied|^\s*(?:error|fatal)\b[:\s]|^FAIL(?:ED)?\b"
    r"|traceback \(most recent call last\)"
    # "3 failed" counts; "0 failed" and a bare "failed" in logged text do not.
    r"|\b[1-9]\d* (?:failed|failing|errors?)\b",
    re.IGNORECASE | re.MULTILINE,
)


def looks_failed(content: str, tool_name: str | None = None) -> bool:
    """Heuristic failure flag for tool results (the dataset has no is_error column).

    With no tool_name the shell rules apply, since a shell is the usual source.
    """
    text = content[:4000]
    if _TOOL_ERROR.search(text):
        return True
    return (tool_name is None or tool_name in SHELL_TOOLS) and bool(_SHELL_FAILURE.search(text))


# Claude Code writes slash commands, their output and interrupts into the
# user_prompt column. Only the interrupt is the person speaking.
_HARNESS_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<local-command-",
    "<environment_context>",
    "<system-reminder>",
)


def is_harness_text(content: str) -> bool:
    return content.lstrip().startswith(_HARNESS_PREFIXES)


@dataclass(frozen=True)
class SampleSpec:
    n: int = 20
    seed: str = "s1evals-v1"
    min_tool_calls: int = 100
    min_prompts: int = 3
    max_per_repo: int = 3
    agent: str | None = None
    # Sessions an earlier sample already used. They still count toward the
    # per-repo cap, so the new sample is the old one's continuation in rank order.
    exclude: frozenset[str] = frozenset()


def select_sessions(rows: Iterable[Mapping], spec: SampleSpec) -> list[Mapping]:
    """Deterministic sample with the blog's filters: >=100 tool calls, >=3 user
    prompts, <=3 sessions per repo. Duplicated session ids first collapse to the
    record with the most output tokens, as the dataset card recommends, and
    only then are filtered."""
    best: dict[str, Mapping] = {}
    for r in rows:
        prev = best.get(r["session_id"])
        if prev is None or (r["output_tokens"] or 0) > (prev["output_tokens"] or 0):
            best[r["session_id"]] = r

    def eligible(r: Mapping) -> bool:
        return (
            not r["kind"]
            and (r["tool_call_count"] or 0) >= spec.min_tool_calls
            and (r["prompt_count"] or 0) >= spec.min_prompts
            and (spec.agent is None or r["agent"] == spec.agent)
        )

    def rank(r: Mapping) -> str:
        return hashlib.sha256(f"{spec.seed}:{r['session_id']}".encode()).hexdigest()

    per_repo: Counter[str] = Counter()
    chosen: list[Mapping] = []
    for r in sorted(filter(eligible, best.values()), key=rank):
        repo = r["repo_id"] or f"unknown:{r['session_id']}"
        if per_repo[repo] >= spec.max_per_repo:
            continue
        per_repo[repo] += 1
        if r["session_id"] in spec.exclude:
            continue
        chosen.append(r)
        if len(chosen) == spec.n:
            break
    return chosen


def map_rows(session: Mapping, rows: Iterable[Mapping]) -> tuple[Trace, list[Event]]:
    """Map one session's conversation rows (any order) to the common schema."""
    trace_id = session["session_id"]
    events: list[Event] = []
    seen: set[tuple] = set()
    for r in sorted(rows, key=lambda r: r["turn_number"]):
        # Duplicated session records can repeat identical turns; keep one copy.
        key = (r["turn_number"], r["turn_type"], r["tool_call_id"], r["content"])
        if key in seen:
            continue
        seen.add(key)
        mapped = TURN_MAP.get(r["turn_type"])
        if mapped is None:
            continue
        role, turn_type = mapped
        content = r["content"] or ""
        if role is Role.USER and is_harness_text(content):
            role = Role.SYSTEM
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
            )
        )
    _attach_tool_names(events)
    events = [
        replace(e, is_error=looks_failed(e.content, e.tool_name)) if e.turn_type is TurnType.TOOL_RESULT else e
        for e in events
    ]
    trace = Trace(
        trace_id=trace_id,
        source=SOURCE,
        repo=session["repo_id"],
        agent=session["agent"],
        model=session["model"] or None,
        n_events=len(events),
        n_tokens=sum(e.tokens for e in events),
        outcome=None if session.get("session_success") in (None, "") else str(session["session_success"]),
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


_FETCH_WORKERS = 16


def _hf_parquet(name: str, columns: list[str], session_ids: list[str] | None = None) -> list[dict]:
    """Read columns of one parquet file; with session_ids, read only the row
    groups that contain them. The session_id column is scanned first (small,
    dictionary-encoded), so the wide `content` column travels only for the
    row groups that hold sampled sessions. Row groups are fetched in parallel:
    one at a time, the ~1,200 small reads alone take minutes over HTTP."""
    from concurrent.futures import ThreadPoolExecutor

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem

    fs, path = HfFileSystem(), f"{REPO}/{name}"
    with fs.open(path, "rb", block_size=8 * 2**20) as f:
        pf = pq.ParquetFile(f)
        if session_ids is None:
            return pf.read(columns=columns).to_pylist()
        meta = pf.metadata
    wanted = _pa_strings(session_ids)

    def read(group: int, cols: list[str]) -> pa.Table:
        with fs.open(path, "rb", block_size=2**20) as f:
            table = pq.ParquetFile(f, metadata=meta).read_row_group(group, columns=cols)
        return table.filter(pc.is_in(table["session_id"], value_set=wanted))

    with ThreadPoolExecutor(_FETCH_WORKERS) as pool:
        hits = pool.map(lambda g: read(g, ["session_id"]).num_rows > 0, range(meta.num_row_groups))
        groups = [g for g, hit in enumerate(hits) if hit]
        tables = list(pool.map(lambda g: read(g, columns), groups))
    return pa.concat_tables(tables).to_pylist() if tables else []


def _pa_strings(values: list[str]):
    import pyarrow as pa

    return pa.array(values, type=pa.string())


def fetch_sample(spec: SampleSpec) -> list[tuple[Trace, list[Event]]]:
    return _fetch(select_sessions(_hf_parquet("sessions.parquet", SESSION_COLUMNS), spec))


def fetch_sessions(session_ids: list[str]) -> list[tuple[Trace, list[Event]]]:
    """Exactly these sessions, e.g. the traces an experiment log lists."""
    wanted = set(session_ids)
    best: dict[str, dict] = {}
    for r in _hf_parquet("sessions.parquet", SESSION_COLUMNS):
        prev = best.get(r["session_id"])
        if r["session_id"] in wanted and (prev is None or (r["output_tokens"] or 0) > (prev["output_tokens"] or 0)):
            best[r["session_id"]] = r
    missing = wanted - set(best)
    if missing:
        raise KeyError(f"sessions not in SWE-chat: {sorted(missing)[:5]}")
    return _fetch([best[i] for i in session_ids])


def _fetch(sessions: list[Mapping]) -> list[tuple[Trace, list[Event]]]:
    ids = [s["session_id"] for s in sessions]
    rows = _hf_parquet("conversations.parquet", CONVERSATION_COLUMNS, ids)
    by_session: dict[str, list[dict]] = {i: [] for i in ids}
    for r in rows:
        by_session[r["session_id"]].append(r)
    return [map_rows(s, by_session[s["session_id"]]) for s in sessions]
