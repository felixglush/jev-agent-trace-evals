"""One pure extractor per rubric: events -> Evidence | Decided | Missing.

Extractors make no model calls. Each returns structured state with named
fields (what a person would look at to answer the rubric's question) and the
event seqs it read, so every verdict can point back to its evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable

from s1evals.domain import SHELL_TOOLS, Decided, Event, Evidence, Missing, SliceResult, TurnType
from s1evals.text import estimate_tokens, head, tail

Extractor = Callable[[list[Event]], SliceResult]
REGISTRY: dict[str, Extractor] = {}

DESTRUCTIVE = re.compile(
    r"\brm\s+(-[a-z]*[rf]|--(recursive|force)\b)|git\s+push\s+[^|;&]*(--force|-f\b)|reset\s+--hard"
    r"|\bdrop\s+(table|database|schema)\b|git\s+clean\s+-[a-z]*f|git\s+checkout\s+--\s|git\s+branch\s+-D",
    re.IGNORECASE,
)
TEST_OR_BUILD = re.compile(
    r"\b(pytest|unittest|tox|nox|jest|vitest|mocha|go\s+test|cargo\s+(test|build|check)|"
    r"npm\s+(run\s+)?(test|build)|pnpm\s+(run\s+)?(test|build)|yarn\s+(test|build)|make\b|"
    r"mvn\s|gradle|tsc\b|bun\s+test|dotnet\s+(test|build)|ctest|swift\s+(test|build))",
    re.IGNORECASE,
)


def extractor(rubric_id: str) -> Callable[[Extractor], Extractor]:
    def register(fn: Extractor) -> Extractor:
        REGISTRY[rubric_id] = fn
        return fn

    return register


# --- helpers ------------------------------------------------------------------


def evidence(state: dict, refs: list[int], target: int | None = None) -> Evidence:
    return Evidence(state=state, refs=tuple(refs), tokens=estimate_tokens(json.dumps(state)), target=target)


# Token room for a slice's text, under the default 4K budget with space left
# for field names. Extractors that list many items share it between them.
SLICE_TOKENS = 3400


def shared_cap(texts: list[str], budget: int, lo: int, hi: int) -> int:
    """The per-text token cap that fits the texts into budget: short texts keep
    all their words and only the longest ones are cut (water-filling)."""
    sizes = sorted(estimate_tokens(t) for t in texts)
    left = budget
    for i, size in enumerate(sizes):
        if size * (len(sizes) - i) > left:
            return max(lo, min(hi, left // (len(sizes) - i)))
        left -= size
    return hi


def user_messages(events: list[Event]) -> list[Event]:
    return [e for e in events if e.is_user_message and e.content.strip()]


def assistant_messages(events: list[Event]) -> list[Event]:
    return [e for e in events if e.is_assistant_message and e.content.strip()]


def shell_command(e: Event) -> str | None:
    if e.turn_type is not TurnType.TOOL_CALL or e.tool_name not in SHELL_TOOLS:
        return None
    if e.command:
        return e.command
    try:
        payload = json.loads(e.content)
    except (json.JSONDecodeError, TypeError):
        return e.content or None
    cmd = payload.get("command") or payload.get("cmd") if isinstance(payload, dict) else None
    return " ".join(cmd) if isinstance(cmd, list) else cmd


def result_of(events: list[Event], call: Event) -> Event | None:
    if call.tool_call_id:
        for e in events:
            if e.turn_type is TurnType.TOOL_RESULT and e.tool_call_id == call.tool_call_id:
                return e
    nxt = next((e for e in events if e.seq > call.seq), None)
    return nxt if nxt and nxt.turn_type is TurnType.TOOL_RESULT else None


def previous(events: list[Event], seq: int, pred: Callable[[Event], bool]) -> Event | None:
    return next((e for e in reversed(events) if e.seq < seq and pred(e)), None)


def following(events: list[Event], seq: int, pred: Callable[[Event], bool]) -> Event | None:
    return next((e for e in events if e.seq > seq and pred(e)), None)


def stable_pick(trace_id: str, salt: str, items: list[Event]) -> Event:
    """Deterministic, trace-specific choice of one target item."""
    h = int(hashlib.sha256(f"{salt}:{trace_id}".encode()).hexdigest(), 16)
    return items[h % len(items)]


def end_of_turn_messages(events: list[Event]) -> list[Event]:
    """Assistant messages that close a turn: the last one before each user message, and the final one."""
    out, last = [], None
    for e in events:
        if e.is_assistant_message and e.content.strip():
            last = e
        elif e.is_user_message and last is not None:
            out.append(last)
            last = None
    if last is not None:
        out.append(last)
    return out


def is_action(e: Event) -> bool:
    return e.is_assistant_message or e.turn_type is TurnType.TOOL_CALL


# --- design-doc rubrics -------------------------------------------------------------


@extractor("task_type")
def task_type(events: list[Event]) -> SliceResult:
    users = user_messages(events)[:2]
    if not users:
        return Missing("trace has no user message")
    return evidence(
        {"opening_user_messages": [head(u.content, 800) for u in users]},
        [u.seq for u in users],
    )


@extractor("user_correction")
def user_correction(events: list[Event]) -> SliceResult:
    users = user_messages(events)
    if len(users) <= 1:
        return Decided("none", "only one user message, so nothing to correct")
    follow_ups = users[1:]
    befores = [
        previous(events, u.seq, lambda e: e.is_assistant_message and bool(e.content.strip())) for u in follow_ups
    ]
    room = SLICE_TOKENS - 100 - 15 * len(follow_ups)  # first request and field names
    user_cap = shared_cap([u.content for u in follow_ups], room * 11 // 20, lo=15, hi=400)
    agent_cap = shared_cap([b.content for b in befores if b], room * 9 // 20, lo=10, hi=500)
    exchanges, refs = [], []
    for u, before in zip(follow_ups, befores, strict=True):
        exchanges.append(
            {
                "agent_said_before": tail(before.content, agent_cap) if before else None,
                "user_follow_up": head(u.content, user_cap),
            }
        )
        refs += [before.seq, u.seq] if before else [u.seq]
    return evidence({"first_request": head(users[0].content, 300), "follow_ups": exchanges}, refs)


@extractor("user_frustration")
def user_frustration(events: list[Event]) -> SliceResult:
    users = user_messages(events)
    if not users:
        return Missing("trace has no user message")
    cap = shared_cap([u.content for u in users], SLICE_TOKENS - 10 * len(users), lo=15, hi=250)
    return evidence({"user_messages_in_order": [head(u.content, cap) for u in users]}, [u.seq for u in users])


MAX_FAILURES = 15


def rerun_outcome(events: list[Event], failure: Event) -> str | None:
    """What happened when the exact same command ran again after this failure.

    A fact code can settle, so the judge doesn't have to find the rerun itself.
    None for tools without a command (an edit, a read).
    """
    if not failure.command:
        return None
    later = [
        e
        for e in events
        if e.seq > failure.seq and e.turn_type is TurnType.TOOL_RESULT and e.command == failure.command
    ]
    if not later:
        return "not run again"
    return "failed again" if all(e.is_error for e in later) else "succeeded later"


@extractor("unrecovered_tool_error")
def unrecovered_tool_error(events: list[Event]) -> SliceResult:
    failures = [e for e in events if e.turn_type is TurnType.TOOL_RESULT and e.is_error]
    if not failures:
        return Decided("no", "no tool result looks failed")
    # An unrecovered error is one still standing at the end, so when there are
    # many failures the latest ones are kept and the earlier ones only counted.
    shown = failures[-MAX_FAILURES:]
    nexts = [following(events, f.seq, is_action) for f in shown]
    room = SLICE_TOKENS - 100 - 50 * len(shown)  # final message, commands and field names
    cap = shared_cap([f.content for f in shown] + [n.content for n in nexts if n], room, lo=20, hi=150)
    items, refs = [], []
    for f, nxt in zip(shown, nexts, strict=True):
        items.append(
            {
                "failed_tool": f.tool_name,
                "command": head(f.command, 30) if f.command else None,
                "error_output": head(f.content, cap),
                "agent_next_action": head(nxt.content, cap) if nxt else "(session ended)",
                "same_command_later": rerun_outcome(events, f),
            }
        )
        refs += [f.seq] + ([nxt.seq] if nxt else [])
    final = assistant_messages(events)[-1:] or []
    return evidence(
        {
            "earlier_failures_not_shown": len(failures) - len(shown),
            "failures_in_order": items,
            "agent_final_message": tail(final[0].content, 300) if final else None,
        },
        refs + [m.seq for m in final],
    )


@extractor("destructive_without_confirmation")
def destructive_without_confirmation(events: list[Event]) -> SliceResult:
    hits = [(e, cmd) for e in events if (cmd := shell_command(e)) and DESTRUCTIVE.search(cmd)]
    if not hits:
        return Decided("n/a", "no destructive shell command was run")
    befores = [previous(events, e.seq, lambda x: x.is_user_message) for e, _ in hits]
    room = SLICE_TOKENS - 20 * len(hits)
    cmd_cap = shared_cap([cmd for _, cmd in hits], room // 3, lo=20, hi=200)
    user_cap = shared_cap([b.content for b in befores if b], room * 2 // 3, lo=20, hi=400)
    items, refs = [], []
    for (e, cmd), before in zip(hits, befores, strict=True):
        items.append(
            {
                "destructive_command": head(cmd, cmd_cap),
                "latest_user_message_before_it": head(before.content, user_cap) if before else None,
            }
        )
        refs += [e.seq] + ([before.seq] if before else [])
    return evidence({"destructive_commands": items}, refs)


@extractor("final_claim_matches_evidence")
def final_claim_matches_evidence(events: list[Event]) -> SliceResult:
    finals = assistant_messages(events)
    if not finals:
        return Missing("trace has no assistant message")
    final = finals[-1]
    checks = [(e, cmd) for e in events if (cmd := shell_command(e)) and TEST_OR_BUILD.search(cmd)]
    if not checks:
        return Decided("n/a", "no test or build command ran, so there is no evidence to compare against")
    call, cmd = checks[-1]
    result = result_of(events, call)
    return evidence(
        {
            "agent_final_message": tail(final.content, 600),
            "last_test_or_build_command": head(cmd, 200),
            "its_output": tail(result.content, 600) if result else "(no output recorded)",
        },
        [call.seq] + ([result.seq] if result else []) + [final.seq],
    )


@extractor("task_completed")
def task_completed(events: list[Event]) -> SliceResult:
    users, finals = user_messages(events), assistant_messages(events)
    if not users or not finals:
        return Missing("trace lacks a user or assistant message")
    state = {
        "first_user_request": head(users[0].content, 400),
        "last_user_message": head(users[-1].content, 400),
        "agent_last_message": tail(finals[-1].content, 600),
    }
    refs = [users[0].seq, users[-1].seq, finals[-1].seq]
    commits = [e for e in events if (cmd := shell_command(e)) and re.search(r"git\s+commit", cmd)]
    if commits:
        result = result_of(events, commits[-1])
        if result:
            state["last_commit_output"] = head(result.content, 200)
            refs.append(result.seq)
    return evidence(state, refs)


# --- Judgment Labs blog rubrics --------------------------------------------------------


@extractor("explicit_constraint")
def explicit_constraint(events: list[Event]) -> SliceResult:
    users = user_messages(events)[:3]
    if not users:
        return Missing("trace has no user message")
    return evidence({"first_user_messages": [head(u.content, 600) for u in users]}, [u.seq for u in users])


@extractor("command_purpose")
def command_purpose(events: list[Event]) -> SliceResult:
    calls = [e for e in events if shell_command(e)]
    if not calls:
        return Decided("n/a", "no shell command was run")
    target = stable_pick(events[0].trace_id, "command_purpose", calls)
    return evidence({"shell_command": head(shell_command(target) or "", 300)}, [target.seq], target=target.seq)


def _pick_assistant_message(events: list[Event], salt: str) -> Event | None:
    candidates = [e for e in assistant_messages(events) if e.tokens >= 15]
    return stable_pick(events[0].trace_id, salt, candidates) if candidates else None


@extractor("assistant_plan")
def assistant_plan(events: list[Event]) -> SliceResult:
    target = _pick_assistant_message(events, "assistant_plan")
    if target is None:
        return Missing("no substantive assistant message")
    return evidence({"assistant_message": head(target.content, 1200)}, [target.seq], target=target.seq)


@extractor("assistant_hedging")
def assistant_hedging(events: list[Event]) -> SliceResult:
    target = _pick_assistant_message(events, "assistant_hedging")
    if target is None:
        return Missing("no substantive assistant message")
    return evidence({"assistant_message": head(target.content, 1200)}, [target.seq], target=target.seq)


@extractor("completion_claim")
def completion_claim(events: list[Event]) -> SliceResult:
    ends = end_of_turn_messages(events)
    if not ends:
        return Missing("no end-of-turn assistant message")
    target = stable_pick(events[0].trace_id, "completion_claim", ends)
    return evidence({"end_of_turn_message": tail(target.content, 1200)}, [target.seq], target=target.seq)
