# 2026-11-27-swechat-20-items

Same 20 traces; unrecovered_tool_error and user_correction v3 with per-item Jev questions aggregated in code

20 traces × 2 rubrics = 40 evals. 0 judge problems (see `problems.jsonl`).

## Agreement with the Claude agent (full trace)

The agent plays the role of the blog's gold labels (Opus 5.5 on the full trajectory).

| Setup | Overall |
| --- | --- |
| Jev on slice (code labels where decided) | 41.0% (16/39) |
| Claude on slice (code labels where decided) | 97.4% (38/39) |
| Routed, only pairs that stayed on the fast path | 70.0% (7/10) |
| Routed: Jev, falling back to the agent (circular on fallbacks) | 92.5% (37/40) |

The routed setup agrees by construction wherever it fell back; the fast-path row is the honest one.

### Per rubric

| Rubric | Source | Jev pipeline | Claude slice pipeline | Fast path only |
| --- | --- | --- | --- | --- |
| unrecovered_tool_error | design-doc | 31.6% (6/19) | 94.7% (18/19) | 57.1% (4/7) |
| user_correction | design-doc | 50.0% (10/20) | 100.0% (20/20) | 100.0% (3/3) |

## Routing

Fallback rate: 75.0% (Gate 2 bar: under 15%).

| Route | Count |
| --- | --- |
| fallback:low_confidence | 29 |
| fast | 7 |
| code | 3 |
| fallback:over_budget | 1 |

## Cost and latency (model usage only)

| Judge | Evals | $ per 1,000 evals | Median latency (s) |
| --- | --- | --- | --- |
| claude_agent | 40 | 144.1599 | 8.96 |
| claude_slice | 36 | 54.5833 | 3.34 |
| jev | 36 | 0.3132 | 0.13 |

Claude costs are per session, split evenly across the rubrics judged in that session.

## Jev calibration against the agent

| Confidence | n | Mean confidence | Accuracy |
| --- | --- | --- | --- |
| [0.0, 0.5) | 29 | 0.28 | 0.31 |
| [0.5, 0.7) | 4 | 0.59 | 0.25 |
| [0.7, 0.8) | 0 | – | – |
| [0.8, 0.9) | 2 | 0.87 | 1.00 |
| [0.9, 1.0] | 1 | 0.90 | 1.00 |

## Confident errors (Jev confidence ≥ 0.8, disagrees with agent): 0


## Gate 1 on this sample

| Rubric | Evidence / code / missing | Slice tokens p50 / p95 | Bounded | Sufficiency (slice vs full) | Sufficient |
| --- | --- | --- | --- | --- | --- |
| unrecovered_tool_error | 17 / 3 / 0 | 2973 / 4001 | no | 15/17 | no |
| user_correction | 20 / 0 / 0 | 3194 / 3866 | yes | 20/20 | yes |

Sufficiency leaves out code-decided pairs and counts a missing slice as a mismatch; passing needs ≥95% on ≥10 pairs.
