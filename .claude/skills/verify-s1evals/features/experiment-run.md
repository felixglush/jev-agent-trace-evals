# Experiment run

## Sub-features
- `s1evals experiment run`: slices, then Jev (one call per rubric), Claude on slices (one session per trace), the Claude agent on the full trace (one session per trace). Resumable by run id.
- `s1evals experiment report <run_id>`: recompute metrics after new human feedback.

## How to get to it (user POV)
Run, then read `experiments/<run_id>/REPORT.md`.

## Driving it with the CLI
`uv run s1evals experiment run --run-id verify-fixtures` on the fixtures takes about 30 s. End state: `REPORT.md` has agreement, routing, cost, calibration and Gate 1 tables; `verdicts.jsonl` has ~19 jev, ~19 claude_slice and ~22 claude_agent rows; `problems.jsonl` is empty.

## Gotchas
Re-running the same run id skips finished work; delete the run's scores to redo it. Claude costs are split evenly across rubrics in a session.
