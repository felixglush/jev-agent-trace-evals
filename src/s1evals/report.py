"""Render RunMetrics as JSON and as the experiment's REPORT.md."""

from __future__ import annotations

from s1evals import analysis
from s1evals.analysis import AGENT, FAST_PIPELINE, ROUTED, SLICE_PIPELINE, Agreement, RunMetrics
from s1evals.rubrics import Rubric

SETUP_NAMES = {
    FAST_PIPELINE: "Jev on slice (code labels where decided)",
    SLICE_PIPELINE: "Claude on slice (code labels where decided)",
    AGENT: "Claude agent on full trace",
    ROUTED: "Routed: Jev, falling back to the agent",
}


def _pct(a: Agreement) -> str:
    return "–" if a.rate is None else f"{100 * a.rate:.1f}% ({a.matched}/{a.total})"


def metrics_json(m: RunMetrics) -> dict:
    def agree(table: dict[str, dict[str, Agreement]]) -> dict:
        return {
            s: {r: {"matched": a.matched, "total": a.total, "rate": a.rate} for r, a in rows.items()}
            for s, rows in table.items()
        }

    return {
        "n_traces": m.n_traces,
        "n_pairs": m.n_pairs,
        "agreement_vs_agent": agree(m.agreement_vs_agent),
        "agreement_vs_human": agree(m.agreement_vs_human),
        "routes": {str(k): v for k, v in m.routes.items()},
        "fallback_rate": analysis.fallback_rate(m.routes),
        "routes_by_rubric": {r: {str(k): v for k, v in c.items()} for r, c in m.routes_by_rubric.items()},
        "calibration": m.calibration,
        "confident_errors": m.confident_errors,
        "cost": m.cost,
        "gate1": m.gate1,
        "label_distribution": {s: {r: dict(c) for r, c in d.items()} for s, d in m.label_distribution.items()},
    }


def markdown(run_id: str, description: str, rubrics: dict[str, Rubric], m: RunMetrics, n_problems: int) -> str:
    rids = sorted({k[1] for k in m.labels[AGENT]} | set(m.routes_by_rubric))
    out = [f"# {run_id}", "", description, "", f"{m.n_traces} traces × {len(rids)} rubrics = {m.n_pairs} evals. "
           f"{n_problems} judge problems (see `problems.jsonl`).", ""]  # fmt: skip

    out += ["## Agreement with the Claude agent (full trace)", "",
            "The agent plays the role of the blog's gold labels (Opus 5.5 on the full trajectory).", "",
            "| Setup | Overall |", "| --- | --- |"]  # fmt: skip
    for setup, rows in m.agreement_vs_agent.items():
        out.append(f"| {SETUP_NAMES[setup]} | {_pct(rows['_all'])} |")
    out += ["", "The routed setup agrees by construction wherever it fell back, so read it with the fallback rate.", ""]

    out += [
        "### Per rubric",
        "",
        "| Rubric | Source | Jev pipeline | Claude slice pipeline | Routed |",
        "| --- | --- | --- | --- | --- |",
    ]
    for rid in rids:
        cells = [_pct(m.agreement_vs_agent[s][rid]) for s in (FAST_PIPELINE, SLICE_PIPELINE, ROUTED)]
        out.append(f"| {rid} | {rubrics[rid].source} | {' | '.join(cells)} |")

    if m.agreement_vs_human:
        out += ["", "## Agreement with human feedback", "", "| Setup | Overall |", "| --- | --- |"]
        for setup, rows in m.agreement_vs_human.items():
            out.append(f"| {SETUP_NAMES[setup]} | {_pct(rows['_all'])} |")

    out += ["", "## Routing", "", f"Fallback rate: {100 * analysis.fallback_rate(m.routes):.1f}% (Gate 2 bar: under 15%).", "",
            "| Route | Count |", "| --- | --- |"]  # fmt: skip
    out += [f"| {r} | {n} |" for r, n in sorted(m.routes.items(), key=lambda x: -x[1])]

    out += ["", "## Cost and latency (model usage only)", "", "| Judge | Evals | $ per 1,000 evals | Median latency (s) |",
            "| --- | --- | --- | --- |"]  # fmt: skip
    for judge, c in sorted(m.cost.items()):
        out.append(f"| {judge} | {c['n']} | {c['usd_per_1000']:.4f} | {c['median_latency_s']:.2f} |")
    out += ["", "Claude costs are per session, split evenly across the rubrics judged in that session."]

    out += [
        "",
        "## Jev calibration against the agent",
        "",
        "| Confidence | n | Mean confidence | Accuracy |",
        "| --- | --- | --- | --- |",
    ]
    for row in m.calibration:
        mc = "–" if row["mean_confidence"] is None else f"{row['mean_confidence']:.2f}"
        acc = "–" if row["accuracy"] is None else f"{row['accuracy']:.2f}"
        out.append(f"| {row['bucket']} | {row['n']} | {mc} | {acc} |")

    out += ["", f"## Confident errors (Jev confidence ≥ 0.8, disagrees with agent): {len(m.confident_errors)}", ""]
    if m.confident_errors:
        out += ["| Trace | Rubric | Jev | Confidence | Agent |", "| --- | --- | --- | --- | --- |"]
        out += [
            f"| {e['trace_id'][:8]} | {e['rubric_id']} | {e['jev']} | {e['confidence']} | {e['agent']} |"
            for e in m.confident_errors
        ]

    out += ["", "## Gate 1 on this sample", "",
            "| Rubric | Evidence / code / missing | Slice tokens p50 / p95 | Bounded | Sufficiency (slice vs full) | Sufficient |",
            "| --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for rid in rids:
        g = m.gate1.get(rid)
        if g:
            out.append(f"| {rid} | {g['evidence']} / {g['decided_by_code']} / {g['missing']} | {g['slice_tokens_p50']} / "
                       f"{g['slice_tokens_p95']} | {'yes' if g['bounded'] else 'no'} | {g['sufficiency']} | "
                       f"{'yes' if g['sufficient'] else 'no'} |")  # fmt: skip
    out += ["", "Sufficiency counts only traces where both a slice label and an agent label exist."]
    return "\n".join(out) + "\n"
