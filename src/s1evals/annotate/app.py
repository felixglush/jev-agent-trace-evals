"""Annotation app: browse traces, see how each rubric was applied by every judge,
and save human labels and comments per trace and rubric.

A small JSON API over the store plus one static page. Human labels saved here
become the reference set for `s1evals experiment report`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from s1evals import rubrics as rubrics_mod
from s1evals import slices as slices_mod
from s1evals.domain import Decided, Evidence, JudgeName, Missing
from s1evals.routing import resolve, route
from s1evals.store import TRACE_NOTE, Feedback, Store

STATIC = Path(__file__).parent / "static"
LIST_MAX_CHARS = 2000


class FeedbackIn(BaseModel):
    trace_id: str
    rubric_id: str
    human_label: str | None = None
    comment: str | None = None


def _slice_json(result) -> dict:
    match result:
        case Evidence(state=state, refs=refs, tokens=tokens, target=target):
            return {"kind": "evidence", "state": state, "refs": list(refs), "tokens": tokens, "target": target}
        case Decided(label=label, reason=reason):
            return {"kind": "decided", "label": label, "reason": reason, "refs": []}
        case Missing(reason=reason):
            return {"kind": "missing", "reason": reason, "refs": []}


def create_app(store: Store, rubrics_dir: Path, author: str) -> FastAPI:
    app = FastAPI(title="s1evals annotate")
    store.init()

    def rubrics():
        return rubrics_mod.load(rubrics_dir)

    def latest_run(run_id: str | None) -> str | None:
        runs = store.run_ids()
        return run_id or (runs[-1] if runs else None)

    @app.get("/api/meta")
    def meta() -> dict:
        return {"author": author, "runs": store.run_ids()}

    @app.get("/api/traces")
    def traces() -> list[dict]:
        fb = store.feedback()
        done: dict[str, int] = {}
        for f in fb:
            if f.rubric_id != TRACE_NOTE and f.human_label:
                done[f.trace_id] = done.get(f.trace_id, 0) + 1
        noted = {f.trace_id for f in fb if f.rubric_id == TRACE_NOTE and f.comment}
        return [
            {**t.__dict__, "labelled": done.get(t.trace_id, 0), "has_note": t.trace_id in noted} for t in store.traces()
        ]

    @app.get("/api/traces/{trace_id}")
    def trace(trace_id: str, run_id: str | None = None) -> dict:
        try:
            t, events = store.trace(trace_id), store.events(trace_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        run_id = latest_run(run_id)
        verdicts = (
            {(v.rubric_id, v.judge): v for _, v in store.scores(run_id=run_id, trace_id=trace_id)} if run_id else {}
        )
        feedback = {f.rubric_id: f for f in store.feedback(trace_id) if f.author == author}
        rubric_rows = []
        for r in rubrics().values():
            s = store.get_slice(trace_id, r.id, r.version) or slices_mod.extract(r, events)
            jev, agent = verdicts.get((r.id, JudgeName.JEV)), verdicts.get((r.id, JudgeName.CLAUDE_AGENT))
            err = None if jev or not isinstance(s, Evidence) else "no fast verdict"
            decision = resolve(route(r, s, jev, err, enforce_admission=False), agent)
            fb = feedback.get(r.id)
            rubric_rows.append(
                {
                    "id": r.id,
                    "version": r.version,
                    "source": r.source,
                    "question": r.question,
                    "kind": r.kind.value,
                    "scope": r.scope.value,
                    "labels": r.labels,
                    "code_labels": r.code_labels,
                    "all_labels": r.all_labels,
                    "evidence": r.evidence,
                    "threshold": r.threshold,
                    "admitted": r.admitted,
                    "slice": _slice_json(s),
                    "route": {"route": decision.route.value, "label": decision.label, "reason": decision.reason},
                    "verdicts": {
                        j.value: {**verdicts[(r.id, j)].__dict__, "judge": j.value}
                        for j in (JudgeName.JEV, JudgeName.CLAUDE_SLICE, JudgeName.CLAUDE_AGENT)
                        if (r.id, j) in verdicts
                    },
                    "feedback": {"human_label": fb.human_label, "comment": fb.comment} if fb else None,
                }
            )
        note = feedback.get(TRACE_NOTE)
        return {
            "trace": t.__dict__,
            "run_id": run_id,
            "events": [
                {
                    "seq": e.seq,
                    "role": e.role.value,
                    "turn_type": e.turn_type.value,
                    "tool_name": e.tool_name,
                    "command": e.command,
                    "is_error": e.is_error,
                    "tokens": e.tokens,
                    "content": e.content[:LIST_MAX_CHARS],
                    "truncated": len(e.content) > LIST_MAX_CHARS,
                }
                for e in events
            ],
            "rubrics": rubric_rows,
            "note": note.comment if note else "",
        }

    @app.get("/api/traces/{trace_id}/events/{seq}")
    def event(trace_id: str, seq: int) -> dict:
        match = [e for e in store.events(trace_id) if e.seq == seq]
        if not match:
            raise HTTPException(404, f"no event {seq}")
        return {"seq": seq, "content": match[0].content}

    @app.post("/api/feedback")
    def save_feedback(body: FeedbackIn) -> dict:
        valid = rubrics()
        if body.rubric_id != TRACE_NOTE:
            if body.rubric_id not in valid:
                raise HTTPException(400, f"unknown rubric {body.rubric_id}")
            if body.human_label and body.human_label not in valid[body.rubric_id].all_labels:
                raise HTTPException(400, f"label {body.human_label!r} not in {valid[body.rubric_id].all_labels}")
        now = datetime.now(UTC).replace(tzinfo=None)
        store.put_feedback(
            Feedback(body.trace_id, body.rubric_id, body.human_label or None, body.comment or None, author, now)
        )
        return {"saved": True, "updated_at": now.isoformat()}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
