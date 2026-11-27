"""DuckDB store: traces, events, slices, scores and human feedback in one file.

Connections are opened per operation so the CLI, the annotation app and the
slow-judge subprocesses never hold a long-lived write lock on the file.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from s1evals.domain import (
    Decided,
    Event,
    Evidence,
    JudgeName,
    Missing,
    Role,
    SliceResult,
    Trace,
    TurnType,
    Verdict,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    repo VARCHAR,
    agent VARCHAR,
    model VARCHAR,
    n_events INTEGER NOT NULL,
    n_tokens INTEGER NOT NULL,
    outcome VARCHAR
);
CREATE TABLE IF NOT EXISTS events (
    trace_id VARCHAR NOT NULL,
    seq INTEGER NOT NULL,
    role VARCHAR NOT NULL,
    turn_type VARCHAR NOT NULL,
    tool_name VARCHAR,
    tool_call_id VARCHAR,
    command VARCHAR,
    is_error BOOLEAN NOT NULL,
    content VARCHAR NOT NULL,
    tokens INTEGER NOT NULL,
    PRIMARY KEY (trace_id, seq)
);
CREATE TABLE IF NOT EXISTS slices (
    trace_id VARCHAR NOT NULL,
    rubric_id VARCHAR NOT NULL,
    rubric_version INTEGER NOT NULL,
    kind VARCHAR NOT NULL,
    state_json VARCHAR,
    refs INTEGER[],
    tokens INTEGER,
    reason VARCHAR,
    PRIMARY KEY (trace_id, rubric_id, rubric_version)
);
CREATE TABLE IF NOT EXISTS scores (
    run_id VARCHAR NOT NULL,
    trace_id VARCHAR NOT NULL,
    rubric_id VARCHAR NOT NULL,
    judge VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    confidence DOUBLE,
    probabilities_json VARCHAR,
    evidence_ref INTEGER[],
    explanation VARCHAR,
    judge_version VARCHAR NOT NULL,
    cost_usd DOUBLE NOT NULL,
    latency_s DOUBLE NOT NULL,
    input_tokens INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (run_id, trace_id, rubric_id, judge)
);
CREATE TABLE IF NOT EXISTS feedback (
    trace_id VARCHAR NOT NULL,
    rubric_id VARCHAR NOT NULL,
    human_label VARCHAR,
    comment VARCHAR,
    author VARCHAR NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (trace_id, rubric_id, author)
);
"""

# rubric_id used for whole-trace feedback rows.
TRACE_NOTE = "_trace"


@dataclass(frozen=True)
class Feedback:
    trace_id: str
    rubric_id: str
    human_label: str | None
    comment: str | None
    author: str
    updated_at: datetime


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(self.path), read_only=read_only)
        try:
            if not read_only:
                con.execute(SCHEMA)
            yield con
        finally:
            con.close()

    def init(self) -> None:
        with self.connect():
            pass

    # --- traces & events ----------------------------------------------------

    def put_trace(self, trace: Trace, events: list[Event]) -> None:
        """Replace one trace and its events (idempotent re-load)."""
        with self.connect() as con:
            con.execute("BEGIN")
            con.execute("DELETE FROM events WHERE trace_id = ?", [trace.trace_id])
            con.execute("DELETE FROM traces WHERE trace_id = ?", [trace.trace_id])
            con.execute(
                "INSERT INTO traces VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    trace.trace_id,
                    trace.source,
                    trace.repo,
                    trace.agent,
                    trace.model,
                    trace.n_events,
                    trace.n_tokens,
                    trace.outcome,
                ],
            )
            con.executemany(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        e.trace_id,
                        e.seq,
                        e.role.value,
                        e.turn_type.value,
                        e.tool_name,
                        e.tool_call_id,
                        e.command,
                        e.is_error,
                        e.content,
                        e.tokens,
                    ]
                    for e in events
                ],
            )
            con.execute("COMMIT")

    def traces(self) -> list[Trace]:
        with self.connect(read_only=True) as con:
            rows = con.execute(
                "SELECT trace_id, source, repo, agent, model, n_events, n_tokens, outcome FROM traces ORDER BY trace_id"
            ).fetchall()
        return [Trace(*r) for r in rows]

    def trace(self, trace_id: str) -> Trace:
        matches = [t for t in self.traces() if t.trace_id == trace_id]
        if not matches:
            raise KeyError(f"unknown trace {trace_id!r}")
        return matches[0]

    def events(self, trace_id: str) -> list[Event]:
        with self.connect(read_only=True) as con:
            rows = con.execute(
                "SELECT trace_id, seq, role, turn_type, tool_name, tool_call_id, command, "
                "is_error, content, tokens FROM events WHERE trace_id = ? ORDER BY seq",
                [trace_id],
            ).fetchall()
        if not rows:
            raise KeyError(f"no events for trace {trace_id!r}")
        return [
            Event(
                trace_id=r[0],
                seq=r[1],
                role=Role(r[2]),
                turn_type=TurnType(r[3]),
                tool_name=r[4],
                tool_call_id=r[5],
                command=r[6],
                is_error=r[7],
                content=r[8],
                tokens=r[9],
            )
            for r in rows
        ]

    # --- slices -------------------------------------------------------------

    def put_slice(self, trace_id: str, rubric_id: str, version: int, result: SliceResult) -> None:
        match result:
            case Evidence(state=state, refs=refs, tokens=tokens, target=target):
                row = ["evidence", json.dumps({"state": state, "target": target}), list(refs), tokens, None]
            case Decided(label=label, reason=reason):
                row = ["decided", json.dumps({"label": label}), [], 0, reason]
            case Missing(reason=reason):
                row = ["missing", None, [], 0, reason]
        with self.connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO slices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [trace_id, rubric_id, version, *row],
            )

    def get_slice(self, trace_id: str, rubric_id: str, version: int) -> SliceResult | None:
        with self.connect(read_only=True) as con:
            row = con.execute(
                "SELECT kind, state_json, refs, tokens, reason FROM slices "
                "WHERE trace_id = ? AND rubric_id = ? AND rubric_version = ?",
                [trace_id, rubric_id, version],
            ).fetchone()
        if row is None:
            return None
        kind, state_json, refs, tokens, reason = row
        if kind == "evidence":
            payload = json.loads(state_json)
            return Evidence(payload["state"], tuple(refs), tokens, payload["target"])
        if kind == "decided":
            return Decided(json.loads(state_json)["label"], reason)
        return Missing(reason)

    # --- scores -------------------------------------------------------------

    def put_scores(self, run_id: str, verdicts: Iterable[Verdict]) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            [
                run_id,
                v.trace_id,
                v.rubric_id,
                v.judge.value,
                v.label,
                v.confidence,
                json.dumps(v.probabilities),
                list(v.evidence_ref),
                v.explanation,
                v.judge_version,
                v.cost_usd,
                v.latency_s,
                v.input_tokens,
                now,
            ]
            for v in verdicts
        ]
        if not rows:
            return
        with self.connect() as con:
            con.executemany(
                "INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def scores(self, run_id: str | None = None, trace_id: str | None = None) -> list[tuple[str, Verdict]]:
        where, params = [], []
        if run_id is not None:
            where.append("run_id = ?")
            params.append(run_id)
        if trace_id is not None:
            where.append("trace_id = ?")
            params.append(trace_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect(read_only=True) as con:
            rows = con.execute(
                "SELECT run_id, trace_id, rubric_id, judge, label, confidence, probabilities_json, "
                "evidence_ref, explanation, judge_version, cost_usd, latency_s, input_tokens "
                f"FROM scores {clause} ORDER BY trace_id, rubric_id, judge",
                params,
            ).fetchall()
        return [
            (
                r[0],
                Verdict(
                    trace_id=r[1],
                    rubric_id=r[2],
                    judge=JudgeName(r[3]),
                    label=r[4],
                    confidence=r[5],
                    probabilities=json.loads(r[6]) if r[6] else {},
                    evidence_ref=tuple(r[7] or ()),
                    explanation=r[8],
                    judge_version=r[9],
                    cost_usd=r[10],
                    latency_s=r[11],
                    input_tokens=r[12],
                ),
            )
            for r in rows
        ]

    def run_ids(self) -> list[str]:
        with self.connect(read_only=True) as con:
            return [r[0] for r in con.execute("SELECT DISTINCT run_id FROM scores ORDER BY run_id").fetchall()]

    # --- feedback -----------------------------------------------------------

    def put_feedback(self, fb: Feedback) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO feedback VALUES (?, ?, ?, ?, ?, ?)",
                [fb.trace_id, fb.rubric_id, fb.human_label, fb.comment, fb.author, fb.updated_at],
            )

    def feedback(self, trace_id: str | None = None) -> list[Feedback]:
        clause, params = ("WHERE trace_id = ?", [trace_id]) if trace_id else ("", [])
        with self.connect(read_only=True) as con:
            rows = con.execute(
                "SELECT trace_id, rubric_id, human_label, comment, author, updated_at "
                f"FROM feedback {clause} ORDER BY trace_id, rubric_id",
                params,
            ).fetchall()
        return [Feedback(*r) for r in rows]
