"""Run an experiment over stored traces and write its log to `experiments/<run_id>/`.

The run is resumable: a (trace, rubric, judge) already scored under the same
run_id is skipped, so re-running after a crash converges to the same end state.

Log files (safe for a public repo: ids, labels, numbers, no trace text):
  config.json      what ran: traces, rubrics + versions, judges, models
  verdicts.jsonl   one line per verdict, without explanations
  routes.jsonl     the routing decision per (trace, rubric)
  metrics.json     analysis.compute() output
  problems.jsonl   judge failures and invalid outputs (kind only; messages stay in data/)
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
from s1evals.domain import Evidence, JudgeName, Missing, SliceResult
from s1evals.judges import claude
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


def _done(store: Store, run_id: str, rubrics: dict[str, Rubric]) -> set[tuple[str, str, JudgeName]]:
    """Pairs already scored in this run at the current rubric versions. A run id
    reused after a rubric changed is refused rather than silently mixed."""
    done = set()
    for _, v in store.scores(run_id=run_id):
        rubric = rubrics.get(v.rubric_id)
        if rubric is None:
            continue
        if not v.judge_version.startswith(f"{rubric.id}@v{rubric.version}/"):
            raise ValueError(
                f"run {run_id!r} has {v.rubric_id} scores at {v.judge_version.split('/')[0]}, but the rubric is now "
                f"v{rubric.version}; use a new --run-id"
            )
        done.add((v.trace_id, v.rubric_id, v.judge))
    return done


class Problems:
    """Judge failures. Full messages (which may quote trace text) stay in the
    gitignored data dir; the public log keeps only who, where and what kind."""

    def __init__(self, path: Path):
        self.path = path

    def add(self, judge: JudgeName, trace_id: str, kind: str, error: str, rubric_id: str | None = None) -> None:
        row = {"judge": judge.value, "trace_id": trace_id, "rubric_id": rubric_id, "kind": kind, "error": error}
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def public(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
        return [{k: v for k, v in r.items() if k != "error"} for r in rows]


def run(store: Store, rubrics: dict[str, Rubric], cfg: RunConfig, data_dir: Path, log: Log = print) -> Path:
    rubrics = {rid: rubrics[rid] for rid in cfg.rubric_ids}
    judges = [JudgeName(j) for j in cfg.judges]
    payload_dir = data_dir / "runs" / cfg.run_id
    payload_dir.mkdir(parents=True, exist_ok=True)
    problems = Problems(payload_dir / "problems.jsonl")
    done = _done(store, cfg.run_id, rubrics)

    log(f"extracting {len(rubrics)} rubrics x {len(cfg.trace_ids)} traces")
    slice_map = extract_all(store, rubrics, cfg.trace_ids)

    def todo(judge: JudgeName, keep: Callable[[analysis.Key], bool]) -> dict[str, list[analysis.Key]]:
        by_trace: dict[str, list[analysis.Key]] = {}
        for k in slice_map:
            if (k[0], k[1], judge) not in done and keep(k):
                by_trace.setdefault(k[0], []).append(k)
        return by_trace

    def in_budget(k: analysis.Key) -> bool:
        s = slice_map[k]
        return isinstance(s, Evidence) and s.tokens <= rubrics[k[1]].budget_tokens

    def agent_can_judge(k: analysis.Key) -> bool:
        # An item rubric with no target item has nothing for the agent to judge.
        return not (rubrics[k[1]].scope is Scope.ITEM and isinstance(slice_map[k], Missing))

    if JudgeName.JEV in judges:
        keys = [k for ks in todo(JudgeName.JEV, in_budget).values() for k in ks]
        _run_jev(store, rubrics, slice_map, keys, cfg.run_id, payload_dir, problems, log)
    if JudgeName.CLAUDE_SLICE in judges:
        jobs = {
            tid: (lambda tid=tid, ks=ks: claude.judge_slices(tid, [(rubrics[r], slice_map[(tid, r)]) for _, r in ks]))
            for tid, ks in todo(JudgeName.CLAUDE_SLICE, in_budget).items()
        }
        _run_sessions(store, cfg, problems, log, JudgeName.CLAUDE_SLICE, jobs)
    if JudgeName.CLAUDE_AGENT in judges:
        jobs = {}
        for tid, ks in todo(JudgeName.CLAUDE_AGENT, agent_can_judge).items():
            snap = payload_dir / "snapshots" / f"{tid}.json"
            snapshot.write(snap, store.trace(tid), store.events(tid))  # main thread, before any worker starts
            targets = [(rubrics[r], getattr(slice_map[(tid, r)], "target", None)) for _, r in ks]
            jobs[tid] = lambda tid=tid, snap=snap, targets=targets: claude.judge_full_trace(tid, snap, targets)
        _run_sessions(store, cfg, problems, log, JudgeName.CLAUDE_AGENT, jobs)

    return write_log(store, rubrics, cfg, slice_map, problems.public())


def _run_jev(store, rubrics, slice_map, keys, run_id, payload_dir, problems: Problems, log) -> None:
    log(f"jev: {len(keys)} calls")
    judge = JevJudge()
    with ThreadPoolExecutor(max_workers=8) as pool, (payload_dir / "jev_requests.jsonl").open("a") as f:
        futures = {pool.submit(judge.judge, rubrics[k[1]], k[0], slice_map[k]): k for k in keys}
        for fut in as_completed(futures):
            k = futures[fut]
            try:
                verdict, payload = fut.result()
            except Exception as exc:  # noqa: BLE001 - one failed call must not end the run
                problems.add(JudgeName.JEV, k[0], type(exc).__name__, str(exc), k[1])
                continue
            store.put_scores(run_id, [verdict])
            f.write(json.dumps({"trace_id": k[0], "rubric_id": k[1], "request": payload}) + "\n")


def _run_sessions(store, cfg, problems: Problems, log, judge: JudgeName, jobs: dict[str, Callable]) -> None:
    """One Claude session per trace, `cfg.workers` at a time. Workers never
    touch the store; scores are written here, on the calling thread."""
    log(f"{judge.value}: {len(jobs)} sessions")
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        futures = {pool.submit(job): tid for tid, job in jobs.items()}
        for i, fut in enumerate(as_completed(futures), 1):
            tid = futures[fut]
            try:
                verdicts, issues = fut.result()
            except Exception as exc:  # noqa: BLE001 - one failed session must not end the run
                problems.add(judge, tid, type(exc).__name__, str(exc))
                log(f"  {judge.value} {i}/{len(futures)} {tid}: FAILED {type(exc).__name__}")
                continue
            store.put_scores(cfg.run_id, verdicts)
            for rubric_id, issue in issues:
                problems.add(judge, tid, "invalid_output", issue, rubric_id)
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
