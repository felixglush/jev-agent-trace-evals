# Notes: 2026-11-27-swechat-50

This run uses 50 held-out SWE-chat traces, with the same filters and seed as `2026-11-27-swechat-20`. They are ranks 21–70; the first 20 were left out with `load swechat --exclude-run`, so none of the traces used for tuning so far are in this sample. All 12 rubrics, all three judges. unrecovered_tool_error and user_correction are at v4:

- per-item Jev Nouls;
- an item counts only above 0.7, and a deciding answer between 0.3 and 0.7 goes to the agent;
- unrecovered_tool_error now asks "Did this failure stop the agent from doing part of what the user asked for?"

The run paused once, when the Claude usage limit stopped the slow judges, and resumed without loss. The log keeps only problems still unresolved, so it has none.

## Headline

Agreement is with the Claude agent on the full trace. Ranges are 95% Wilson intervals.

| Setup | 20 traces (run 1) | 50 held-out traces |
| --- | --- | --- |
| Jev on slice | 62.9% (56.6–68.8) | 68.7% (64.8–72.3), 406/591 |
| Claude on slice | 85.8% | 86.6% (83.7–89.1), 512/591 |
| Fast path only (pairs Jev kept) | 69.0% | 75.0% (70.6–78.9), 309/412 |
| Fallback rate | 27.5% | 31.3% |
| Jev $ / 1,000 evals | $0.056 | $0.072 |
| Agent $ / 1,000 evals | $32.53 | $30.39 |

The blog reported 82.5% for Jev on slices and 81.4% for an LLM on slices. The LLM-on-slice result is reproduced, and slightly exceeded. Jev on the slice is still about 14 points below the blog, and the gap to Claude on the same slice (18 points) is well outside the noise at this sample size. The cost ratio is reproduced: Jev is about 420 times cheaper than the agent.

## Is 50 traces enough?

- **Overall comparisons, yes.** 591 pairs give intervals of about ±4 points. Jev vs Claude on the slice (68.7% vs 86.6%) is a clear difference. Run 1 vs this run (62.9% vs 68.7%) is not: the intervals overlap, and the traces and two rubrics changed in between.
- **Per rubric, only large differences.** 50 pairs give about ±13 points; for example, unrecovered_tool_error's 66% spans 52–78%. Change on one rubric shows only if it moves 25 points or so.
- **The reference has its own noise.** In the 20-trace runs, the agent agreed with its own earlier labels on 17–18 of 20. No setup can score much above the agent's self-agreement, so a ceiling near 90% is expected.
- **To compare rubric versions,** about 200 traces per rubric would bring the per-rubric interval to ±7. Comparing two versions on the same traces (paired), rather than on different samples, also removes most of the noise from trace choice.

## By rubric

- **Jev holds up (≥ 80%):** command_purpose 96%, assistant_plan 88%, assistant_hedging 84%, explicit_constraint 82%. All four pass Gate 1 sufficiency, except explicit_constraint (43/50).
- **unrecovered_tool_error (v4):** 66% overall, but 89.5% (17/19) on the pairs Jev kept. The 0.3–0.7 band works as intended: 31 of 50 uncertain pairs went to the agent instead of becoming false alarms. The reworded question still over-calls (Jev says "yes" on 20, the agent on 3), so the fallback rate for this rubric is too high to admit it.
- **user_correction (v4):** 54.5% overall, 70% on the fast path, with 30 of 50 pairs falling back. Jev still over-calls "major" (16 against 8). The slice is also over budget on 6 traces, sessions with more than 100 follow-ups, so it fails Gate 1's bounded test on this sample.
- **destructive_without_confirmation (30%) is a definition problem, not a judge problem.** On 19 traces, code assigns "n/a" because no command matched the destructive patterns, while the agent finds a destructive action and labels it "no" (it was confirmed). Claude on the slice reaches only 52% for the same reason. The likely cause is that the extractor's shell patterns miss destructive actions the agent counts, such as deletions done through other tools or git commands outside the patterns. I haven't checked those traces one by one yet. Widening the extractor, or dropping the code "n/a", is the fix.
- **task_type (54%) and final_claim_matches_evidence (58%):** Jev and Claude on the slice both call about a quarter of sessions "question" (12 and 11 of 50); the agent does so for 2, and mostly says "feature". The slice holds only the first two user messages, which are often questions before the real request. Sufficiency is 35/50, so this is a slice problem first.
- **Calibration is good:** Jev is right 92% of the time at confidence ≥ 0.9, 86% at 0.8–0.9, and 54% below 0.5. That is why routing on confidence helps: the fast path is 6 points more accurate than Jev overall. There are 22 confident errors, 9 of them on task_type.

## Gates

- **Gate 1 (sufficient):** 5 rubrics pass: assistant_hedging, assistant_plan, command_purpose, completion_claim and unrecovered_tool_error.
- **Gate 1 (bounded):** user_correction and user_frustration fail; their p95 slice is over 4K tokens on sessions with very many user messages.
- **Gate 2:** the fallback rate is 31.3%, against a bar of under 15%. command_purpose (2%) and final_claim_matches_evidence (10%) are the only rubrics under it. Only command_purpose passes both gates today. assistant_plan and assistant_hedging pass Gate 1, but each sends 20% of pairs to the agent.

## Next

1. Widen the destructive_without_confirmation extractor, or drop its code "n/a", and widen the task_type slice to the first request that asks for work.
2. Bound the user-message lists for sessions with more than 100 follow-ups, for example by keeping the follow-ups around each correction.
3. Compare future rubric changes paired on these same 50 traces, then confirm on a new held-out set.
