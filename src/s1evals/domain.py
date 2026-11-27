"""Core data shapes shared by every layer: traces, events, slices, verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Tool names that run shell commands, across the agents in SWE-chat.
SHELL_TOOLS = frozenset({"Bash", "bash", "shell", "exec_command", "run_shell_command", "local_shell"})


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class TurnType(StrEnum):
    MESSAGE = "message"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


@dataclass(frozen=True)
class Event:
    trace_id: str
    seq: int
    role: Role
    turn_type: TurnType
    content: str
    tokens: int
    tool_name: str | None = None
    tool_call_id: str | None = None
    command: str | None = None
    is_error: bool = False

    @property
    def is_user_message(self) -> bool:
        return self.role is Role.USER and self.turn_type is TurnType.MESSAGE

    @property
    def is_assistant_message(self) -> bool:
        return self.role is Role.ASSISTANT and self.turn_type is TurnType.MESSAGE


@dataclass(frozen=True)
class Trace:
    trace_id: str
    source: str
    repo: str | None
    agent: str | None
    model: str | None
    n_events: int
    n_tokens: int
    outcome: str | None = None


# --- Slices -----------------------------------------------------------------
# An extractor returns exactly one of these three outcomes. The router reads
# the variant, so "no evidence" can never be confused with "evidence says no".


@dataclass(frozen=True)
class Evidence:
    """Structured state for the fast judge plus the event seqs it came from.

    `target` names the one event an item-level rubric judges (e.g. the shell
    command picked for "command purpose"); trace-level rubrics leave it None.
    """

    state: dict
    refs: tuple[int, ...]
    tokens: int
    target: int | None = None


@dataclass(frozen=True)
class Decided:
    """Code settles the label without a model (e.g. no shell calls -> n/a)."""

    label: str
    reason: str


@dataclass(frozen=True)
class Missing:
    """Evidence should exist but the extractor could not find it."""

    reason: str


SliceResult = Evidence | Decided | Missing


# --- Verdicts ---------------------------------------------------------------


class JudgeName(StrEnum):
    CODE = "code"
    JEV = "jev"
    CLAUDE_SLICE = "claude_slice"
    CLAUDE_AGENT = "claude_agent"


@dataclass(frozen=True)
class Verdict:
    trace_id: str
    rubric_id: str
    judge: JudgeName
    label: str
    confidence: float | None
    judge_version: str
    probabilities: dict[str, float] = field(default_factory=dict)
    evidence_ref: tuple[int, ...] = ()
    explanation: str | None = None
    cost_usd: float = 0.0
    latency_s: float = 0.0
    input_tokens: int = 0
