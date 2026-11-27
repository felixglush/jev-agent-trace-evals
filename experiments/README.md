# Experiment logs

One folder per run, written by `uv run s1evals experiment run --run-id <id>` and refreshed by `uv run s1evals experiment report <id>` (for example after new human feedback in the annotation app).

| File | Contents |
| --- | --- |
| `REPORT.md` | Agreement, routing, cost, calibration, confident errors, Gate 1 |
| `config.json` | Traces, rubric versions, judges, models |
| `verdicts.jsonl` | One line per verdict (no explanations, no trace text) |
| `routes.jsonl` | Routing decision and final label per (trace, rubric) |
| `metrics.json` | Machine-readable metrics |
| `problems.jsonl` | Judge failures and invalid outputs |
| `NOTES.md` | Written analysis of the run, when present |

## Runs

| Run | Traces | What |
| --- | --- | --- |
