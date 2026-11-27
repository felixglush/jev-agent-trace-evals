# Notes: 2026-11-27-swechat-20

The first real run: 20 SWE-chat sessions picked with the blog's filters (≥100 tool calls, ≥3 prompts, ≤3 per repo, seed `s1evals-v1`), 12 rubrics, three judges. The numbers are in `REPORT.md` and `metrics.json`. This file says what they mean.

## Headline vs the Judgment Labs blog

| | Blog (256 traces, 6 rubrics) | This run (20 traces, 12 rubrics) |
| --- | --- | --- |
| Jev on slice, agreement with full-trace labels | 82.5% | 62.9% (151/240) |
| LLM on slice | 81.4% | 85.8% (206/240) |
| Jev, $ per 1,000 evals | $0.04 | $0.056 |
| LLM on full trace, $ per 1,000 evals | $21.76 | $32.53 |

The cost side matches the blog: Jev is about 580× cheaper than the full-trace agent, with a median latency of 0.1 s. The accuracy side does not match yet. Claude reading the same slice agrees with the full-trace agent 85.8% of the time, which shows the slices hold enough evidence for most rubrics. The 23-point gap is between the two judges reading the same slice, not between slice and full trace.

Caveats: 20 traces give 20 pairs per rubric, so one pair moves a per-rubric number by 5 points. The reference labels come from one Claude agent pass, not from people. Claude on the slice and the Claude agent are the same model, so they may share biases that flatter the slice pipeline.

## Where Jev diverges

- **unrecovered_tool_error (30%).** Jev answers "yes" on 16 of 20 traces; the agent says "yes" on 2. The slice lists up to 15 failures with the agent's next action after each. Jev seems to answer "was there a failure?" rather than "was a failure left unfixed?". Asking one question per failure ("was this failure fixed or worked around?") and aggregating in code should suit it better, as the blog does with item-level questions.
- **user_correction (50%).** Jev says "none" on 13 traces, the agent on 6. Most of the gap is "minor" corrections that Jev misses in long lists of follow-ups. A per-follow-up question ("does this message correct the agent?") would be the same fix as above.
- **completion_claim (45%).** This is an item rubric on one end-of-turn message. Jev picks "partial" 8 times where the agent says "complete" or "no_claim". The label wording for partial versus complete needs tightening.
- **explicit_constraint (60%).** The agent says "yes" on 19 of 20 and Jev on 11. The agent reads the whole session and finds constraints anywhere; the slice holds only the first three user messages. That is a slice problem as much as a judge problem; Claude on the slice also only reaches 70%.
- **destructive_without_confirmation (60%).** Jev flags 8 destructive commands as unconfirmed; the agent flags 2. Most of these are routine cleanup (`rm -rf` of build output) that the agent treats as harmless.

Jev is strong on user_frustration (100% on the fast path), command_purpose (80%) and assistant_plan (82% on the fast path).

## Calibration and routing

Jev's confidence is informative: at ≥0.8 it agrees with the agent 87% of the time (74/85 pairs), and below 0.5 only 47%. The 0.5 threshold sends 66 of 240 pairs (27.5%) to the agent, above the design doc's 15% bar for Gate 2. Pairs that stay on the fast path agree 69.0% of the time. There are 11 confident errors (≥0.8 and wrong), 3 of them on completion_claim.

## Gate 1

Every rubric's slice is now bounded (p95 under 4K tokens). That took one round of fixes before this run (commit "fit real SWE-chat traces into the slice budget"). Before them, user_correction ran over budget on 17 of 20 traces, because of a noisy failure flag, slash-command text counted as user messages, and unbounded lists.

Sufficiency (Claude on the slice vs Claude on the full trace, ≥95%) passes for 5 rubrics: assistant_hedging, assistant_plan, final_claim_matches_evidence, task_completed and user_frustration. task_type (14/20) and explicit_constraint (14/20) are the weakest slices. Both read only the first user messages, and the agent often decides from later context.

## Next

1. Split unrecovered_tool_error and user_correction into per-item questions with a code aggregate. Done in `2026-11-27-swechat-20-items`: it did not raise agreement (see that run's NOTES.md).
2. Tighten completion_claim's partial/complete wording, using the TypeSafe skill's question-writing guidance.
3. Widen the task_type and explicit_constraint slices to all user messages, sized to the budget.
4. Label a few traces by hand in the annotation app (`s1evals annotate`), so agreement can also be measured against people.
