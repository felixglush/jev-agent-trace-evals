"""Claude judges, run through headless Claude Code (`claude -p`).

- `claude_slice`: Claude reads the same slices Jev reads, no tools. This is the
  blog's "LLM on preprocessed evidence" setup and the Gate 1 sufficiency probe.
- `claude_agent`: the slow judge. Claude explores the full trace with read-only
  tools (`s1evals trace ...` bound to a snapshot of one trace) and returns a
  label, a short explanation and the event seqs it relied on.

Both judge every requested rubric for one trace in a single session to keep
the agent's exploration shared; each verdict is still one rubric's label.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from s1evals.domain import Evidence, JudgeName, Verdict
from s1evals.judges import JudgeError
from s1evals.rubrics import Rubric, Scope

MODEL = "opus"
EFFORT = "medium"
TRACE_TOOL_PREFIX = "s1evals trace"


def output_schema(rubrics: list[Rubric], with_evidence: bool) -> dict:
    item = {
        "type": "object",
        "properties": {
            "rubric_id": {"type": "string", "enum": [r.id for r in rubrics]},
            "label": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "explanation": {"type": "string"},
        },
        "required": ["rubric_id", "label", "confidence", "explanation"],
    }
    if with_evidence:
        item["properties"]["evidence_seqs"] = {"type": "array", "items": {"type": "integer"}}
        item["required"].append("evidence_seqs")
    return {
        "type": "object",
        "properties": {"verdicts": {"type": "array", "items": item}},
        "required": ["verdicts"],
    }


def _rubric_block(rubric: Rubric, include_code_labels: bool) -> str:
    labels = dict(rubric.labels)
    if include_code_labels:
        labels.update({k: v for k, v in rubric.code_labels.items() if k not in labels})
    lines = [f"### {rubric.id}", f"Question: {rubric.question}", "Labels:"]
    lines += [f"- {name}: {desc}" for name, desc in labels.items()]
    return "\n".join(lines)


def slice_prompt(items: list[tuple[Rubric, Evidence]]) -> str:
    parts = [
        "You label one coding-agent session against several rubrics. For each rubric you see only "
        "an evidence excerpt taken from the session. Answer each rubric's question from its excerpt "
        "alone, picking exactly one of its labels. Give a confidence from 0 to 1 that your label is "
        "right, and a one-sentence explanation.",
    ]
    for rubric, ev in items:
        parts.append(_rubric_block(rubric, include_code_labels=False))
        parts.append("Evidence:\n```json\n" + json.dumps(ev.state, ensure_ascii=False, indent=1) + "\n```")
    return "\n\n".join(parts)


def agent_prompt(trace_id: str, items: list[tuple[Rubric, int | None]]) -> str:
    parts = [
        f"You are the reference judge for one coding-agent session (trace {trace_id}). Read the session "
        "with these read-only shell commands, and nothing else:\n"
        f"- `{TRACE_TOOL_PREFIX} overview` : counts, user-message seqs, tool usage, failed tool results\n"
        f"- `{TRACE_TOOL_PREFIX} turns [--role user|assistant|tool|system] [--type message|thinking|tool_call|tool_result] "
        "[--start N] [--end M] [--limit K] [--max-chars C]` : events in a seq range\n"
        f'- `{TRACE_TOOL_PREFIX} search "text" [--limit K]` : case-insensitive search\n'
        f"- `{TRACE_TOOL_PREFIX} tool-result SEQ` : one tool call or result with its pair\n\n"
        "Start with the overview, read every user message, then look at whatever each question needs. "
        "Answer each rubric from the whole session, not only the start or the end. Pick exactly one of "
        "its labels. Give a confidence from 0 to 1, a one- or two-sentence explanation, and the seqs of "
        "the events your answer rests on.",
    ]
    for rubric, target in items:
        block = _rubric_block(rubric, include_code_labels=True)
        if rubric.scope is Scope.ITEM and target is not None:
            block += f"\nJudge only the event at seq {target}."
        parts.append(block)
    return "\n\n".join(parts)


@dataclass(frozen=True)
class ClaudeRun:
    structured: dict
    cost_usd: float
    latency_s: float
    raw: dict


def run_claude(
    prompt: str,
    schema: dict,
    *,
    allow_trace_tools: bool,
    env: dict[str, str] | None = None,
    model: str = MODEL,
    effort: str = EFFORT,
    timeout_s: float = 1800,
    cwd: Path | None = None,
) -> ClaudeRun:
    exe = shutil.which("claude")
    if exe is None:
        raise JudgeError("the `claude` CLI is not on PATH")
    cmd = [
        exe, "-p", prompt,
        "--model", model,
        "--effort", effort,
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--no-session-persistence",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--permission-mode", "dontAsk",
    ]  # fmt: skip
    if allow_trace_tools:
        cmd += ["--tools", "Bash", "--allowedTools", f"Bash({TRACE_TOOL_PREFIX}:*)"]
    else:
        cmd += ["--tools", ""]
    full_env = {**os.environ, **(env or {})}
    # Make the `s1evals` entry point of this interpreter's venv resolvable.
    full_env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{full_env.get('PATH', '')}"
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=full_env, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        raise JudgeError(f"claude timed out after {timeout_s}s") from exc
    latency = time.monotonic() - start
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise JudgeError(f"claude returned non-JSON (exit {proc.returncode}): {proc.stderr[-500:]}") from exc
    if raw.get("is_error") or not isinstance(raw.get("structured_output"), dict):
        raise JudgeError(f"claude run failed: {raw.get('subtype')} {str(raw.get('result'))[:300]}")
    return ClaudeRun(raw["structured_output"], float(raw.get("total_cost_usd") or 0.0), latency, raw)


def to_verdicts(
    run: ClaudeRun,
    trace_id: str,
    rubrics: list[Rubric],
    judge: JudgeName,
    refs: dict[str, tuple[int, ...]] | None = None,
) -> tuple[list[Verdict], list[tuple[str | None, str]]]:
    """Map structured output to verdicts. Returns (verdicts, [(rubric_id, problem)])."""
    by_id = {r.id: r for r in rubrics}
    share = 1 / max(len(rubrics), 1)
    verdicts, problems, seen = [], [], set()
    for item in run.structured.get("verdicts", []):
        rid = item.get("rubric_id") if isinstance(item, dict) else None
        rubric = by_id.get(rid)
        if rubric is None or rubric.id in seen:
            problems.append((rid, "unexpected or duplicate verdict"))
            continue
        allowed = rubric.all_labels if judge is JudgeName.CLAUDE_AGENT else list(rubric.labels)
        label = item.get("label")
        if label not in allowed:
            problems.append((rubric.id, f"label {label!r} not in {allowed}"))
            continue
        seen.add(rubric.id)
        evidence_ref = tuple(item.get("evidence_seqs") or ()) or (refs or {}).get(rubric.id, ())
        verdicts.append(
            Verdict(
                trace_id=trace_id,
                rubric_id=rubric.id,
                judge=judge,
                label=label,
                confidence=float(item.get("confidence", 0.0)),
                evidence_ref=tuple(evidence_ref),
                explanation=item.get("explanation"),
                judge_version=rubric.judge_version(judge, f"claude-{MODEL}-{EFFORT}"),
                cost_usd=run.cost_usd * share,
                latency_s=run.latency_s * share,
            )
        )
    problems += [(r.id, "no verdict returned") for r in rubrics if r.id not in seen]
    return verdicts, problems


def judge_slices(
    trace_id: str, items: list[tuple[Rubric, Evidence]]
) -> tuple[list[Verdict], list[tuple[str | None, str]]]:
    rubrics = [r for r, _ in items]
    run = run_claude(slice_prompt(items), output_schema(rubrics, with_evidence=False), allow_trace_tools=False)
    return to_verdicts(run, trace_id, rubrics, JudgeName.CLAUDE_SLICE, refs={r.id: ev.refs for r, ev in items})


def judge_full_trace(
    trace_id: str, snapshot: Path, items: list[tuple[Rubric, int | None]]
) -> tuple[list[Verdict], list[tuple[str | None, str]]]:
    """The agent runs in an empty temp dir holding only this trace's snapshot,
    so nothing reachable from its working directory belongs to other traces
    or to the other judges' answers."""
    rubrics = [r for r, _ in items]
    with tempfile.TemporaryDirectory(prefix="s1evals-judge-") as tmp:
        sandboxed = Path(tmp) / "trace.json"
        shutil.copyfile(snapshot, sandboxed)
        run = run_claude(
            agent_prompt(trace_id, items),
            output_schema(rubrics, with_evidence=True),
            allow_trace_tools=True,
            env={"S1EVALS_SNAPSHOT": str(sandboxed)},
            cwd=Path(tmp),
        )
    return to_verdicts(run, trace_id, rubrics, JudgeName.CLAUDE_AGENT)
