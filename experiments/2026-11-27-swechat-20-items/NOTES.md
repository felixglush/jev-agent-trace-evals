# Notes: 2026-11-27-swechat-20-items

A follow-up to `2026-11-27-swechat-20`. It uses the same 20 traces and covers the two rubrics where Jev did worst there: unrecovered_tool_error (30%) and user_correction (50%). Both rubrics are now v3, and all three judges ran again.

## What changed

Following TypeSafe's guidance (one judgment per question, each item in its own question, decisions in code), Jev no longer answers one question over a list. Each request asks Noul questions about every list entry, and the entry goes into the question. Code in `src/s1evals/judges/aggregate.py` turns the answers into the label:

- **unrecovered_tool_error:** one question per failure: "Was this failed tool call still unresolved when the session ended?" The label is "yes" if any failure scores p ≥ 0.5. The slice now also says, for each failure, whether the same command later succeeded.
- **user_correction:** two questions per follow-up: "Does this user message tell the agent that something it did or said is wrong?" and "Does it say the agent misunderstood the task or took the wrong approach?" The label is major if some follow-up is both, minor if some follow-up is a correction, and none otherwise.

The Claude judges still answer each rubric's own question over the whole slice.

## Result: no gain

| Rubric | Jev, run 1 (one question) | Jev, run 2 (per item) | Claude on slice, run 2 |
| --- | --- | --- | --- |
| unrecovered_tool_error | 30.0% (6/20) | 31.6% (6/19) | 94.7% (18/19) |
| user_correction | 50.0% (10/20) | 50.0% (10/20) | 100.0% (20/20) |

Agreement is with the Claude agent on the full trace, as before. The errors changed direction, but there are no fewer of them:

- **user_correction:** in run 1, Jev missed corrections ("none" on 13 traces, against 6 for the agent). Now it over-calls them ("major" on 11, against 6). Taking the most severe of up to 60 follow-ups means one misread message sets the label. In one checked case, a new request ("review our ...") scored 0.76 on the redirect question.
- **unrecovered_tool_error:** Jev now says "yes" on 13 traces and the agent on 0. The per-failure answers sit around 0.7 to 0.78 for inspection commands that failed harmlessly: a `gh pr diff` or `sed` on a missing path, after which the agent carried on. The true criterion includes "moved on without it", which literally describes these cases. The rubric means a failure that blocked the task, not any failure the agent stepped past. The wording asks the wrong thing.
- **Calibration** got worse: 29 of 39 Jev answers have confidence below 0.5 and are right only 31% of the time. Per-item probabilities cluster in the 0.6 to 0.8 band, which TypeSafe's docs describe as unsettled. A max over many unsettled answers is itself unsettled, so 75% of pairs fell back to the agent.

## Two other findings

- **The reference is noisy too.** The Claude agent labelled the same traces twice, once in each run. It agreed with itself on 18/20 for unrecovered_tool_error and 17/20 for user_correction. With this sample, differences of about 10 points between setups are within the agent's own variance.
- **One slice went over budget** (4,001 tokens against a 4,000 budget), because the per-failure `same_command_later` field added a few tokens. That pair fell back to the agent.

Jev's cost went from $0.06 to $0.31 per 1,000 evals, because each question now carries its item text. That is still about 450 times cheaper than the agent.

## What to try next

These are design changes, not wording tweaks, and they should be checked on traces outside these 20.

1. **unrecovered_tool_error:** ask what the rubric means: "Did this failure stop the agent from doing something the user asked for?" Leave "did the agent move on" out of the criteria.
2. **Aggregate with thresholds instead of 0.5:** count an item only above 0.7, and treat the 0.3 to 0.7 band as "unsettled", sending the pair to the slow judge. TypeSafe's docs suggest 0.7 and 0.3 as starting Noul thresholds.
3. **user_correction:** give the "corrects" question the agent's previous message as named state, rather than as text inside the question, so a new request after a finished task reads as new. Then compare on a fresh sample of 20 traces.
4. **A larger sample:** with 20 pairs and an agent that agrees with itself 85 to 90% of the time, neither run can show a small improvement.
