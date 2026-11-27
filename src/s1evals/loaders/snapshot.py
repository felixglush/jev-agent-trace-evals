"""Common-schema JSON snapshots of a trace: used for fixtures and for the slow
judge's read-only tools, which must not touch the DuckDB file while the parent
process writes scores."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from s1evals.domain import Event, Role, Trace, TurnType


def write(path: Path, trace: Trace, events: list[Event]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"trace": asdict(trace), "events": [asdict(e) for e in events]}
    path.write_text(json.dumps(payload, ensure_ascii=False))


def read(path: Path) -> tuple[Trace, list[Event]]:
    payload = json.loads(Path(path).read_text())
    trace = Trace(**payload["trace"])
    events = [Event(**{**e, "role": Role(e["role"]), "turn_type": TurnType(e["turn_type"])}) for e in payload["events"]]
    return trace, events
