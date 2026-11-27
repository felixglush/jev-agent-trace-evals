"""Run an experiment over stored traces and write its log to `experiments/<run_id>/`.

The run is resumable: a (trace, rubric, judge) already scored under the same
run_id is skipped, so re-running after a crash converges to the same end state.

Log files (safe for a public repo: ids, labels, numbers, no trace text):
  config.json      what ran: traces, rubrics + versions, judges, models
  verdicts.jsonl   one line per verdict, without explanations
  routes.jsonl     the routing decision per (trace, rubric)
  metrics.json     analysis.compute() output
  problems.jsonl   judge failures and invalid outputs
  REPORT.md        human-readable summary
Raw request payloads and explanations stay in the gitignored data dir.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from s1evals import analysis, report, slices
from s1evals.domain import Evidence, JudgeName, Missing, SliceResult, Verdict
from s1evals.judges import JudgeError, claude
from s1evals.judges.jev import JevJudge
from s1evals.loaders import snapshot
from s1evals.paths import REPO_ROOT
from s1evals.routing import resolve, route
from s1evals.rubrics import Rubric, Scope
from s1evals.store import TRACE_NOTE, Store

EXPERIMENTS_DIR = REPO_ROOT / "experiments"
ALL_JUDGES = (JudgeName.JEV, JudgeName.CLAUDE_SLICE, JudgeName.CLAUDE_AGENT)

Log = Callable[[str], None]


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    description: str
    trace_ids: list[str]
    rubric_ids: list[str]
    judges: list[str]
    workers: int = 4


def extract_all(store: Store, rubrics: dict[str, Rubric], trace_ids: list[str]) -> dict[analysis.Key, SliceResult]:
    out = {}
    for tid in trace_ids:
        events = store.events(tid)
        for rubric in rubrics.values():
            result = slices.extract(rubric, events)
            store.put_slice(tid, rubric.id, rubric.version, result)
            out[(tid, rubric.id)] = result
    return out


def _done(store: Store, run_id: str) -> set[tuple[str, str, JudgeName]]:
    return {(v.trace_id, v.rubric_id, v.judge) for _, v in store.scores(run_id=run_id)}


def run(store: Store, rubrics: dict[str, Rubric], cfg: RunConfig, data_dir: Path, log: Log = print) -> Path:
    rubrics = {rid: rubrics[rid] for rid in cfg.rubric_ids}
    judges = [JudgeName(j) for j in cfg.judges]
    payload_dir = data_dir / "runs" / cfg.run_id
    payload_dir.mkdir(parents=True, exist_ok=True)
    problems: list[dict] = []

    log(f"extracting {len(rubrics)} rubrics x {len(cfg.trace_ids)} traces")
    slice_map = extract_all(store, rubrics, cfg.trace_ids)
    done = _done(store, cfg.run_id)

    def todo(judge: JudgeName) -> list[analysis.Key]:
        return [k for k in slice_map if (k[0], k[1], judge) not in done]

    if JudgeName.JEV in judges:
        _run_jev(store, rubrics, slice_map, todo(JudgeName.JEV), cfg, payload_dir, problems, log)
    if JudgeName.CLAUDE_SLICE in judges:
        _run_per_trace(store, cfg, problems, log, JudgeName.CLAUDE_SLICE, todo(JudgeName.CLAUDE_SLICE),
                       lambda tid, keys: claude.judge_slices(
                           tid, [(rubrics[r], slice_map[(tid, r)]) for _, r in keys]),
                       only=lambda k: isinstance(slice_map[k], Evidence))  # fmt: skip
    if JudgeName.CLAUDE_AGENT in judges:
        snap_dir = payload_dir / "snapshots"

        def agent(tid: str, keys: list[analysis.Key]) -> tuple[list[Verdict], list[str]]:
            path = snap_dir / f"{tid}.json"
            snapshot.write(path, store.trace(tid), store.events(tid))
            targets = [(rubrics[r], getattr(slice_map[(tid, r)], "target", None)) for _, r in keys]
            return claude.judge_full_trace(tid, path, targets)

        # An item rubric with no target item has nothing for the agent to judge.
        def judgeable(k: analysis.Key) -> bool:
            return not (rubrics[k[1]].scope is Scope.ITEM and isinstance(slice_map[k], Missing))

        _run_per_trace(store, cfg, problems, log, JudgeName.CLAUDE_AGENT, todo(JudgeName.CLAUDE_AGENT), agent,
                       only=judgeable)  # fmt: skip

    return write_log(store, rubrics, cfg, slice_map, problems)


def _run_jev(store, rubrics, slice_map, keys, cfg, payload_dir, problems, log) -> None:
    keys = [k for k in keys if isinstance(slice_map[k], Evidence)]
    log(f"jev: {len(keys)} calls")
    judge = JevJudge()
    with ThreadPoolExecutor(max_workers=8) as pool, (payload_dir / "jev_requests.jsonl").open("a") as f:
        futures = {pool.submit(judge.judge, rubrics[k[1]], k[0], slice_map[k]): k for k in keys}
        for fut in as_completed(futures):
            k = futures[fut]
            try:
                verdict, payload = fut.result()
            except JudgeError as exc:
                problems.append({"judge": "jev", "trace_id": k[0], "rubric_id": k[1], "error": str(exc)})
                continue
            store.put_scores(cfg.run_id, [verdict])
            f.write(json.dumps({"trace_id": k[0], "rubric_id": k[1], "request": payload}) + "\n")


def _run_per_trace(store, cfg, problems, log, judge, keys, fn, only=lambda k: True) -> None:
    by_trace: dict[str, list[analysis.Key]] = {}
    for k in keys:
        if only(k):
            by_trace.setdefault(k[0], []).append(k)
    log(f"{judge.value}: {len(by_trace)} sessions")
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        futures = {pool.submit(fn, tid, ks): tid for tid, ks in by_trace.items()}
        for i, fut in enumerate(as_completed(futures), 1):
            tid = futures[fut]
            try:
                verdicts, issues = fut.result()
            except JudgeError as exc:
                problems.append({"judge": judge.value, "trace_id": tid, "error": str(exc)})
                log(f"  {judge.value} {i}/{len(futures)} {tid}: FAILED {exc}")
                continue
            store.put_scores(cfg.run_id, verdicts)
            problems += [{"judge": judge.value, "trace_id": tid, "error": p} for p in issues]
            log(f"  {judge.value} {i}/{len(futures)} {tid}: {len(verdicts)} verdicts")


def human_labels(store: Store) -> dict[analysis.Key, str]:
    """Latest human label per (trace, rubric) across authors."""
    out = {}
    for fb in sorted(store.feedback(), key=lambda f: f.updated_at):
        if fb.rubric_id != TRACE_NOTE and fb.human_label:
            out[(fb.trace_id, fb.rubric_id)] = fb.human_label
    return out


def write_log(
    store: Store,
    rubrics: dict[str, Rubric],
    cfg: RunConfig,
    slice_map: dict[analysis.Key, SliceResult],
    problems: list[dict],
    out_root: Path = EXPERIMENTS_DIR,
) -> Path:
    out = out_root / cfg.run_id
    out.mkdir(parents=True, exist_ok=True)
    verdicts = [v for _, v in store.scores(run_id=cfg.run_id)]
    metrics = analysis.compute(rubrics, slice_map, verdicts, human_labels(store))

    config = {
        **asdict(cfg),
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rubric_versions": {r.id: r.version for r in rubrics.values()},
        "models": {"jev": "jev-1.14.0", "claude": f"claude {claude.MODEL} effort={claude.EFFORT}"},
    }
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    with (out / "verdicts.jsonl").open("w") as f:
        for v in verdicts:
            row = {k: val for k, val in asdict(v).items() if k != "explanation"}
            row["evidence_ref"] = list(v.evidence_ref)
            f.write(json.dumps(row) + "\n")
    by = analysis.index(verdicts)
    with (out / "routes.jsonl").open("w") as f:
        for k in sorted(slice_map):
            rubric = rubrics[k[1]]
            jev = by[JudgeName.JEV].get(k)
            err = None if jev or not isinstance(slice_map[k], Evidence) else "no fast verdict"
            d = resolve(
                route(rubric, slice_map[k], jev, err, enforce_admission=False), by[JudgeName.CLAUDE_AGENT].get(k)
            )
            f.write(json.dumps({"trace_id": k[0], "rubric_id": k[1], "route": d.route.value,
                                "label": d.label, "judge": d.judge.value if d.judge else None}) + "\n")  # fmt: skip
    with (out / "problems.jsonl").open("w") as f:
        for p in problems:
            f.write(json.dumps(p) + "\n")
    (out / "metrics.json").write_text(json.dumps(report.metrics_json(metrics), indent=2) + "\n")
    (out / "REPORT.md").write_text(report.markdown(cfg.run_id, cfg.description, rubrics, metrics, len(problems)))
    return out
