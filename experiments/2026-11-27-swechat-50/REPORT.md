# 2026-11-27-swechat-50

Held-out 50 SWE-chat traces (blog filters, ranks 21-70 of seed s1evals-v1), 12 rubrics; per-item Jev for unrecovered_tool_error and user_correction v4

50 traces × 12 rubrics = 600 evals. 0 judge problems (see `problems.jsonl`).

## Agreement with the Claude agent (full trace)

The agent plays the role of the blog's gold labels (Opus 5.5 on the full trajectory).

| Setup | Overall |
| --- | --- |
| Jev on slice (code labels where decided) | 68.7% (406/591) |
| Claude on slice (code labels where decided) | 86.6% (512/591) |
| Routed, only pairs that stayed on the fast path | 75.0% (309/412) |
| Routed: Jev, falling back to the agent (circular on fallbacks) | 82.8% (497/600) |

The routed setup agrees by construction wherever it fell back; the fast-path row is the honest one.

### Per rubric

| Rubric | Source | Jev pipeline | Claude slice pipeline | Fast path only |
| --- | --- | --- | --- | --- |
| assistant_hedging | judgment-labs-blog | 84.0% (42/50) | 98.0% (49/50) | 87.5% (35/40) |
| assistant_plan | judgment-labs-blog | 88.0% (44/50) | 98.0% (49/50) | 92.5% (37/40) |
| command_purpose | judgment-labs-blog | 96.0% (48/50) | 100.0% (50/50) | 95.9% (47/49) |
| completion_claim | judgment-labs-blog | 68.0% (34/50) | 98.0% (49/50) | 71.9% (23/32) |
| destructive_without_confirmation | design-doc | 30.0% (15/50) | 52.0% (26/50) | 30.8% (12/39) |
| explicit_constraint | judgment-labs-blog | 82.0% (41/50) | 86.0% (43/50) | 88.6% (31/35) |
| final_claim_matches_evidence | design-doc | 58.0% (29/50) | 68.0% (34/50) | 57.8% (26/45) |
| task_completed | design-doc | 64.0% (32/50) | 90.0% (45/50) | 72.4% (21/29) |
| task_type | design-doc | 54.0% (27/50) | 70.0% (35/50) | 59.0% (23/39) |
| unrecovered_tool_error | design-doc | 66.0% (33/50) | 96.0% (48/50) | 89.5% (17/19) |
| user_correction | design-doc | 54.5% (24/44) | 84.1% (37/44) | 70.0% (14/20) |
| user_frustration | design-doc | 78.7% (37/47) | 100.0% (47/47) | 92.0% (23/25) |

## Routing

Fallback rate: 31.3% (Gate 2 bar: under 15%).

| Route | Count |
| --- | --- |
| fast | 367 |
| fallback:low_confidence | 179 |
| code | 45 |
| fallback:over_budget | 9 |

## Cost and latency (model usage only)

| Judge | Evals | $ per 1,000 evals | Median latency (s) |
| --- | --- | --- | --- |
| claude_agent | 600 | 30.3890 | 2.37 |
| claude_slice | 546 | 14.8626 | 1.14 |
| jev | 546 | 0.0718 | 0.10 |

Claude costs are per session, split evenly across the rubrics judged in that session.

## Jev calibration against the agent

| Confidence | n | Mean confidence | Accuracy |
| --- | --- | --- | --- |
| [0.0, 0.5) | 179 | 0.29 | 0.54 |
| [0.5, 0.7) | 96 | 0.60 | 0.66 |
| [0.7, 0.8) | 53 | 0.74 | 0.72 |
| [0.8, 0.9) | 86 | 0.85 | 0.86 |
| [0.9, 1.0] | 132 | 0.97 | 0.92 |

## Confident errors (Jev confidence ≥ 0.8, disagrees with agent): 22

| Trace | Rubric | Jev | Confidence | Agent |
| --- | --- | --- | --- | --- |
| 019e5a5c | task_type | question | 0.99 | feature |
| 019eee04 | final_claim_matches_evidence | overclaims | 1.0 | consistent |
| 068bf5f6 | explicit_constraint | no | 0.84 | yes |
| 1da2f5a8 | assistant_plan | yes | 0.8 | no |
| 22bc3bd4 | completion_claim | partial | 0.99 | complete |
| 22bc3bd4 | task_type | refactor | 0.81 | other |
| 23d79622 | task_type | bugfix | 0.98 | feature |
| 5744817a | completion_claim | complete | 1.0 | no_claim |
| 5c45236e | task_type | bugfix | 0.83 | feature |
| 8545cce9 | destructive_without_confirmation | yes | 0.88 | no |
| 8e2b85fd | user_frustration | yes | 0.82 | no |
| 92023f7e | command_purpose | test | 0.84 | run |
| 92023f7e | completion_claim | blocked | 0.93 | no_claim |
| 95a3e71a | task_type | question | 0.93 | other |
| 9a75ddd2 | task_completed | not_done | 0.84 | partial |
| 9a75ddd2 | task_type | question | 0.8 | feature |
| a8ebae0a | task_type | refactor | 0.9 | feature |
| d4677bf5 | completion_claim | partial | 0.99 | complete |
| d4f2fdbb | explicit_constraint | no | 0.86 | yes |
| d4f2fdbb | task_type | question | 1.0 | bugfix |
| e91ffe16 | task_type | other | 0.87 | bugfix |
| ed80b65d | explicit_constraint | no | 0.82 | yes |

## Gate 1 on this sample

| Rubric | Evidence / code / missing | Slice tokens p50 / p95 | Bounded | Sufficiency (slice vs full) | Sufficient |
| --- | --- | --- | --- | --- | --- |
| assistant_hedging | 50 / 0 / 0 | 56 / 722 | yes | 49/50 | yes |
| assistant_plan | 50 / 0 / 0 | 40 / 453 | yes | 49/50 | yes |
| command_purpose | 50 / 0 / 0 | 51 / 229 | yes | 50/50 | yes |
| completion_claim | 50 / 0 / 0 | 262 / 1252 | yes | 49/50 | yes |
| destructive_without_confirmation | 24 / 26 / 0 | 754 / 2656 | yes | 19/24 | no |
| explicit_constraint | 50 / 0 / 0 | 323 / 1293 | yes | 43/50 | no |
| final_claim_matches_evidence | 36 / 14 / 0 | 480 / 1142 | yes | 34/36 | no |
| task_completed | 50 / 0 / 0 | 657 / 1297 | yes | 45/50 | no |
| task_type | 50 / 0 / 0 | 252 / 1201 | yes | 35/50 | no |
| unrecovered_tool_error | 47 / 3 / 0 | 2210 / 3814 | yes | 45/47 | yes |
| user_correction | 48 / 2 / 0 | 2352 / 10363 | no | 35/48 | no |
| user_frustration | 50 / 0 / 0 | 619 / 4653 | no | 47/50 | no |

Sufficiency leaves out code-decided pairs and counts a missing slice as a mismatch; passing needs ≥95% on ≥10 pairs.
