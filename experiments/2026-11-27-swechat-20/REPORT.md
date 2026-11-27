# 2026-11-27-swechat-20

20 SWE-chat traces (blog filters), 12 rubrics, Jev vs Claude Opus 5.5 on slice vs Claude agent on full trace

20 traces × 12 rubrics = 240 evals. 0 judge problems (see `problems.jsonl`).

## Agreement with the Claude agent (full trace)

The agent plays the role of the blog's gold labels (Opus 5.5 on the full trajectory).

| Setup | Overall |
| --- | --- |
| Jev on slice (code labels where decided) | 62.9% (151/240) |
| Claude on slice (code labels where decided) | 85.8% (206/240) |
| Routed, only pairs that stayed on the fast path | 69.0% (120/174) |
| Routed: Jev, falling back to the agent (circular on fallbacks) | 77.5% (186/240) |

The routed setup agrees by construction wherever it fell back; the fast-path row is the honest one.

### Per rubric

| Rubric | Source | Jev pipeline | Claude slice pipeline | Fast path only |
| --- | --- | --- | --- | --- |
| assistant_hedging | judgment-labs-blog | 70.0% (14/20) | 95.0% (19/20) | 73.7% (14/19) |
| assistant_plan | judgment-labs-blog | 75.0% (15/20) | 95.0% (19/20) | 82.4% (14/17) |
| command_purpose | judgment-labs-blog | 80.0% (16/20) | 85.0% (17/20) | 80.0% (16/20) |
| completion_claim | judgment-labs-blog | 45.0% (9/20) | 90.0% (18/20) | 50.0% (8/16) |
| destructive_without_confirmation | design-doc | 60.0% (12/20) | 75.0% (15/20) | 75.0% (9/12) |
| explicit_constraint | judgment-labs-blog | 60.0% (12/20) | 70.0% (14/20) | 66.7% (8/12) |
| final_claim_matches_evidence | design-doc | 75.0% (15/20) | 75.0% (15/20) | 68.8% (11/16) |
| task_completed | design-doc | 65.0% (13/20) | 95.0% (19/20) | 75.0% (6/8) |
| task_type | design-doc | 65.0% (13/20) | 70.0% (14/20) | 75.0% (12/16) |
| unrecovered_tool_error | design-doc | 30.0% (6/20) | 90.0% (18/20) | 35.7% (5/14) |
| user_correction | design-doc | 50.0% (10/20) | 90.0% (18/20) | 46.2% (6/13) |
| user_frustration | design-doc | 80.0% (16/20) | 100.0% (20/20) | 100.0% (11/11) |

## Routing

Fallback rate: 27.5% (Gate 2 bar: under 15%).

| Route | Count |
| --- | --- |
| fast | 155 |
| fallback:low_confidence | 66 |
| code | 19 |

## Cost and latency (model usage only)

| Judge | Evals | $ per 1,000 evals | Median latency (s) |
| --- | --- | --- | --- |
| claude_agent | 240 | 32.5290 | 2.55 |
| claude_slice | 221 | 16.8516 | 1.20 |
| jev | 221 | 0.0559 | 0.10 |

Claude costs are per session, split evenly across the rubrics judged in that session.

## Jev calibration against the agent

| Confidence | n | Mean confidence | Accuracy |
| --- | --- | --- | --- |
| [0.0, 0.5) | 66 | 0.30 | 0.47 |
| [0.5, 0.7) | 40 | 0.58 | 0.45 |
| [0.7, 0.8) | 30 | 0.74 | 0.57 |
| [0.8, 0.9) | 28 | 0.85 | 0.86 |
| [0.9, 1.0] | 57 | 0.97 | 0.88 |

## Confident errors (Jev confidence ≥ 0.8, disagrees with agent): 11

| Trace | Rubric | Jev | Confidence | Agent |
| --- | --- | --- | --- | --- |
| 019f280c | task_completed | not_done | 0.91 | partial |
| 1073c709 | task_type | question | 1.0 | feature |
| 15c46273 | command_purpose | file_change | 0.99 | run |
| 1f4d64e1 | destructive_without_confirmation | yes | 0.88 | no |
| 3689fb8b | task_type | question | 0.94 | other |
| 54b9bee4 | assistant_hedging | certain | 0.87 | no_claims |
| 54b9bee4 | command_purpose | version_control | 0.98 | inspect |
| 73aa526d | completion_claim | partial | 1.0 | no_claim |
| 995a1b1c | completion_claim | partial | 0.91 | complete |
| 995a1b1c | task_type | bugfix | 0.81 | feature |
| da3a18b8 | completion_claim | partial | 0.88 | complete |

## Gate 1 on this sample

| Rubric | Evidence / code / missing | Slice tokens p50 / p95 | Bounded | Sufficiency (slice vs full) | Sufficient |
| --- | --- | --- | --- | --- | --- |
| assistant_hedging | 20 / 0 / 0 | 52 / 370 | yes | 19/20 | yes |
| assistant_plan | 20 / 0 / 0 | 48 / 1283 | yes | 19/20 | yes |
| command_purpose | 19 / 1 / 0 | 34 / 323 | yes | 17/19 | no |
| completion_claim | 20 / 0 / 0 | 303 / 911 | yes | 18/20 | no |
| destructive_without_confirmation | 11 / 9 / 0 | 410 / 2605 | yes | 8/11 | no |
| explicit_constraint | 20 / 0 / 0 | 280 / 1542 | yes | 14/20 | no |
| final_claim_matches_evidence | 14 / 6 / 0 | 498 / 1371 | yes | 14/14 | yes |
| task_completed | 20 / 0 / 0 | 517 / 1055 | yes | 19/20 | yes |
| task_type | 20 / 0 / 0 | 133 / 1338 | yes | 14/20 | no |
| unrecovered_tool_error | 17 / 3 / 0 | 2840 / 3857 | yes | 15/17 | no |
| user_correction | 20 / 0 / 0 | 3194 / 3866 | yes | 18/20 | no |
| user_frustration | 20 / 0 / 0 | 1143 / 3267 | yes | 20/20 | yes |

Sufficiency leaves out code-decided pairs and counts a missing slice as a mismatch; passing needs ≥95% on ≥10 pairs.
