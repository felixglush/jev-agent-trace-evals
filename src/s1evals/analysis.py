"""Metrics over one run's verdicts: agreement, calibration, fallbacks, cost, gates.

Everything here is a pure function of verdicts, slices, rubrics and human
labels, so the same numbers come out of the CLI, the experiment log and tests.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from s1evals.domain import Decided, Evidence, JudgeName, Missing, SliceResult, Verdict
from s1evals.routing import Route, resolve, route
from s1evals.rubrics import Rubric

Key = tuple[str, str]  # (trace_id, rubric_id)

# A "setup" is one way to produce a label for every (trace, rubric) pair.
FAST_PIPELINE = "jev_pipeline"  # code label or Jev on the slice
SLICE_PIPELINE = "claude_slice_pipeline"  # code label or Claude on the slice
AGENT = "claude_agent"  # Claude agent on the full trace
ROUTED = "routed"  # fast pipeline with fallbacks to the agent
FAST_PATH = "fast_path"  # routed labels on pairs that did NOT fall back (non-circular vs the agent)
SUFFICIENCY_MIN_N = 10
SUFFICIENCY_BAR = 0.95  # design doc: at least 19 of 20 slice-only labels match full-trace labels

CALIBRATION_BUCKETS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


@dataclass(frozen=True)
class Agreement:
    matched: int
    total: int

    @property
    def rate(self) -> float | None:
        return self.matched / self.total if self.total else None


@dataclass
class RunMetrics:
    n_traces: int
    n_pairs: int
    labels: dict[str, dict[Key, str]]
    agreement_vs_agent: dict[str, dict[str, Agreement]]
    agreement_vs_human: dict[str, dict[str, Agreement]]
    routes: Counter
    routes_by_rubric: dict[str, Counter]
    calibration: list[dict]
    confident_errors: list[dict]
    cost: dict[str, dict]
    gate1: dict[str, dict]
    label_distribution: dict[str, dict[str, Counter]] = field(default_factory=dict)
    confidence_quality: dict = field(default_factory=dict)


def index(verdicts: list[Verdict]) -> dict[JudgeName, dict[Key, Verdict]]:
    out: dict[JudgeName, dict[Key, Verdict]] = defaultdict(dict)
    for v in verdicts:
        out[v.judge][(v.trace_id, v.rubric_id)] = v
    return out


def pipeline_label(slice_result: SliceResult | None, model_verdict: Verdict | None) -> str | None:
    if isinstance(slice_result, Decided):
        return slice_result.label
    return model_verdict.label if model_verdict else None


def agreement(labels: dict[Key, str], reference: dict[Key, str], rubric_ids: list[str]) -> dict[str, Agreement]:
    out = {}
    for rid in [*rubric_ids, "_all"]:
        keys = [k for k in reference if k in labels and (rid == "_all" or k[1] == rid)]
        out[rid] = Agreement(sum(labels[k] == reference[k] for k in keys), len(keys))
    return out


def compute(
    rubrics: dict[str, Rubric],
    slices: dict[Key, SliceResult],
    verdicts: list[Verdict],
    human: dict[Key, str] | None = None,
) -> RunMetrics:
    human = human or {}
    by = index(verdicts)
    keys = sorted(slices)
    rubric_ids = sorted({k[1] for k in keys})

    labels: dict[str, dict[Key, str]] = {FAST_PIPELINE: {}, SLICE_PIPELINE: {}, AGENT: {}, ROUTED: {}, FAST_PATH: {}}
    routes: Counter = Counter()
    routes_by_rubric: dict[str, Counter] = defaultdict(Counter)
    for k in keys:
        rubric, s = rubrics[k[1]], slices[k]
        jev, cs, agent = by[JudgeName.JEV].get(k), by[JudgeName.CLAUDE_SLICE].get(k), by[JudgeName.CLAUDE_AGENT].get(k)
        for name, value in (
            (FAST_PIPELINE, pipeline_label(s, jev)),
            (SLICE_PIPELINE, pipeline_label(s, cs)),
            (AGENT, agent.label if agent else None),
        ):
            if value is not None:
                labels[name][k] = value
        fast_error = None if jev or not isinstance(s, Evidence) else "no fast verdict recorded"
        decision = resolve(route(rubric, s, jev, fast_error, enforce_admission=False), agent)
        routes[decision.route] += 1
        routes_by_rubric[k[1]][decision.route] += 1
        if decision.label is not None:
            labels[ROUTED][k] = decision.label
            if not decision.route.is_fallback:
                labels[FAST_PATH][k] = decision.label

    agent_ref = labels[AGENT]
    vs_agent = {
        name: agreement(labels[name], agent_ref, rubric_ids)
        for name in (FAST_PIPELINE, SLICE_PIPELINE, FAST_PATH, ROUTED)
    }
    vs_human = {name: agreement(labels[name], human, rubric_ids) for name in labels} if human else {}

    return RunMetrics(
        n_traces=len({k[0] for k in keys}),
        n_pairs=len(keys),
        labels=labels,
        agreement_vs_agent=vs_agent,
        agreement_vs_human=vs_human,
        routes=routes,
        routes_by_rubric=dict(routes_by_rubric),
        calibration=calibration(by[JudgeName.JEV], agent_ref),
        confident_errors=confident_errors(by[JudgeName.JEV], agent_ref),
        confidence_quality=confidence_quality(by[JudgeName.JEV], agent_ref),
        cost=cost_summary(verdicts),
        gate1=gate1(rubrics, slices, labels[SLICE_PIPELINE], agent_ref),
        label_distribution={
            name: {rid: Counter(v for k, v in lab.items() if k[1] == rid) for rid in rubric_ids}
            for name, lab in labels.items()
        },
    )


def calibration(fast: dict[Key, Verdict], reference: dict[Key, str]) -> list[dict]:
    rows = []
    for lo, hi in CALIBRATION_BUCKETS:
        items = [
            (v, reference[k])
            for k, v in fast.items()
            if k in reference and v.confidence is not None and lo <= v.confidence < hi
        ]
        rows.append(
            {
                "bucket": f"[{lo:.1f}, {min(hi, 1.0):.1f}{']' if hi > 1 else ')'}",
                "n": len(items),
                "mean_confidence": statistics.fmean(v.confidence for v, _ in items) if items else None,
                "accuracy": sum(v.label == ref for v, ref in items) / len(items) if items else None,
            }
        )
    return rows


TUNE_MIN_KEPT = 10  # a threshold must keep this many answers before its accuracy counts
COVERAGE_THRESHOLDS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def auroc(scored: list[tuple[float, bool]]) -> float | None:
    """Probability that a right answer has higher confidence than a wrong one
    (ties count half). None when there are no right or no wrong answers."""
    right = [c for c, ok in scored if ok]
    wrong = [c for c, ok in scored if not ok]
    if not right or not wrong:
        return None
    wins = sum((r > w) + 0.5 * (r == w) for r in right for w in wrong)
    return wins / (len(right) * len(wrong))


def confidence_quality(fast: dict[Key, Verdict], reference: dict[Key, str]) -> dict:
    """How well Jev's confidence separates its right answers from its wrong
    ones, and what each routing threshold would keep (risk-coverage)."""
    scored = [
        (v.confidence, v.label == reference[k], k[1])
        for k, v in fast.items()
        if k in reference and v.confidence is not None
    ]
    if not scored:
        return {}
    coverage = []
    for t in COVERAGE_THRESHOLDS:
        kept = [ok for c, ok, _ in scored if c >= t]
        coverage.append(
            {
                "threshold": t,
                "coverage": len(kept) / len(scored),
                "accuracy_kept": sum(kept) / len(kept) if kept else None,
            }
        )
    by_rubric = {}
    for rid in sorted({r for _, _, r in scored}):
        rows = [(c, ok) for c, ok, r in scored if r == rid]
        by_rubric[rid] = {"n": len(rows), "accuracy": sum(ok for _, ok in rows) / len(rows), "auroc": auroc(rows)}
    return {
        "n": len(scored),
        "auroc": auroc([(c, ok) for c, ok, _ in scored]),
        "coverage": coverage,
        "by_rubric": by_rubric,
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson interval for k successes out of n."""
    if not n:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def roc(scored: list[tuple[float, bool]]) -> list[dict]:
    """ROC of confidence as a detector of right answers: at each threshold, the
    share of right answers kept (tpr) against the share of wrong ones kept (fpr)."""
    right = sum(ok for _, ok in scored)
    wrong = len(scored) - right
    points = [{"threshold": None, "tpr": 0.0, "fpr": 0.0}]
    for t in sorted({c for c, _ in scored}, reverse=True):
        kept = [ok for c, ok in scored if c >= t]
        points.append(
            {
                "threshold": t,
                "tpr": sum(kept) / right if right else 0.0,
                "fpr": (len(kept) - sum(kept)) / wrong if wrong else 0.0,
            }
        )
    return points


def sweep(scored: list[tuple[float, bool]]) -> list[dict]:
    """What each threshold keeps on the fast path, and how often that agrees."""
    if not scored:
        return []
    out = []
    for t in sorted({0.0, *(c for c, _ in scored)}):
        kept = [ok for c, ok in scored if c >= t]
        out.append(
            {
                "threshold": t,
                "kept": len(kept),
                "coverage": len(kept) / len(scored),
                "accuracy_kept": sum(kept) / len(kept) if kept else None,
                "interval": wilson(sum(kept), len(kept)),
            }
        )
    return out


def suggest_threshold(scored: list[tuple[float, bool]], target: float, min_kept: int = TUNE_MIN_KEPT) -> float | None:
    """The lowest threshold whose kept answers agree at least `target` of the
    time, i.e. the one that keeps the most pairs on the fast path. None if no
    threshold keeping at least `min_kept` answers reaches the target."""
    ok = [r["threshold"] for r in sweep(scored) if r["kept"] >= min_kept and r["accuracy_kept"] >= target]
    return min(ok) if ok else None


def _apply(scored: list[tuple[float, bool]], t: float | None) -> tuple[int, int]:
    kept = [ok for c, ok in scored if t is not None and c >= t]
    return len(kept), sum(kept)


def tune_thresholds(
    fast: dict[Key, Verdict], reference: dict[Key, str], target: float, current: dict[str, float] | None = None
) -> dict:
    """Per-rubric ROC and threshold choice for Jev's confidence against the
    reference labels. `held_out` tunes on half the traces and scores on the
    other half (both ways), which shows how much a per-rubric threshold
    picked on this sample would overfit."""
    current = current or {}
    pairs = [
        (k[0], k[1], v.confidence, v.label == reference[k])
        for k, v in fast.items()
        if k in reference and v.confidence is not None
    ]
    traces = sorted({t for t, *_ in pairs})
    fold = {t: i % 2 for i, t in enumerate(traces)}

    def report(rows: list[tuple[str, str, float, bool]], cur: float | None) -> dict:
        scored = [(c, ok) for _, _, c, ok in rows]
        held_kept = held_right = 0
        for f in (0, 1):
            t = suggest_threshold([(c, ok) for tid, _, c, ok in rows if fold[tid] != f], target, TUNE_MIN_KEPT // 2)
            k, r = _apply([(c, ok) for tid, _, c, ok in rows if fold[tid] == f], t)
            held_kept, held_right = held_kept + k, held_right + r
        cur_kept, cur_right = _apply(scored, cur)
        return {
            "n": len(scored),
            "accuracy": sum(ok for _, ok in scored) / len(scored),
            "auroc": auroc(scored),
            "roc": roc(scored),
            "sweep": sweep(scored),
            "suggested": suggest_threshold(scored, target),
            "current": cur,
            "current_coverage": cur_kept / len(scored),
            "current_accuracy": cur_right / cur_kept if cur_kept else None,
            "held_out": {
                "coverage": held_kept / len(scored),
                "accuracy_kept": held_right / held_kept if held_kept else None,
            },
        }

    by_rubric = {
        rid: report([p for p in pairs if p[1] == rid], current.get(rid)) for rid in sorted({p[1] for p in pairs})
    }
    return {"target": target, "overall": report(pairs, None) if pairs else None, "by_rubric": by_rubric}


def confident_errors(fast: dict[Key, Verdict], reference: dict[Key, str], floor: float = 0.8) -> list[dict]:
    return [
        {
            "trace_id": k[0],
            "rubric_id": k[1],
            "jev": v.label,
            "confidence": round(v.confidence, 3),
            "agent": reference[k],
        }
        for k, v in sorted(fast.items())
        if k in reference and v.confidence is not None and v.confidence >= floor and v.label != reference[k]
    ]


def cost_summary(verdicts: list[Verdict]) -> dict[str, dict]:
    out = {}
    for judge, vs in index(verdicts).items():
        vals = list(vs.values())
        out[judge.value] = {
            "n": len(vals),
            "usd_per_1000": 1000 * statistics.fmean(v.cost_usd for v in vals) if vals else 0.0,
            "median_latency_s": statistics.median(v.latency_s for v in vals) if vals else 0.0,
            "mean_input_tokens": statistics.fmean(v.input_tokens for v in vals) if vals else 0.0,
        }
    return out


def gate1(
    rubrics: dict[str, Rubric], slices: dict[Key, SliceResult], slice_labels: dict[Key, str], agent: dict[Key, str]
) -> dict[str, dict]:
    """Gate 1 measurements on the sample: addressable, bounded, sufficient.

    Sufficiency compares Claude reading only the slice with the Claude agent
    reading the full trace, standing in for "relabel reading only the slice".
    Code-decided pairs are left out (no model read them); a Missing slice counts
    as a mismatch. Passing needs at least 95% agreement on at least 10 pairs.
    """
    out = {}
    for rid, rubric in rubrics.items():
        rs = {k: s for k, s in slices.items() if k[1] == rid}
        if not rs:
            continue
        tokens = sorted(s.tokens for s in rs.values() if isinstance(s, Evidence))
        missing = [k[0] for k, s in rs.items() if isinstance(s, Missing)]
        judged = [k for k, s in rs.items() if k in agent and not isinstance(s, Decided)]
        matched = sum(slice_labels.get(k) == agent[k] for k in judged)
        p95 = tokens[min(len(tokens) - 1, int(0.95 * len(tokens)))] if tokens else 0
        out[rid] = {
            "n": len(rs),
            "evidence": len(tokens),
            "decided_by_code": sum(isinstance(s, Decided) for s in rs.values()),
            "missing": len(missing),
            "missing_traces": missing,
            "slice_tokens_p50": tokens[len(tokens) // 2] if tokens else 0,
            "slice_tokens_p95": p95,
            "bounded": p95 <= rubric.budget_tokens,
            "sufficiency": f"{matched}/{len(judged)}",
            "sufficient": len(judged) >= SUFFICIENCY_MIN_N and matched / len(judged) >= SUFFICIENCY_BAR,
        }
    return out


def fallback_rate(routes: Counter) -> float:
    total = sum(routes.values())
    return sum(n for r, n in routes.items() if Route(r).is_fallback) / total if total else 0.0
