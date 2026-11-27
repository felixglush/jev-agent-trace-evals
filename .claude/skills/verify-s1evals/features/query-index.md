# Evals as indexes

## Sub-features
`s1evals query "<sql>"` exposes `trace_labels` (one column per rubric, routed labels), plus `traces`, `events`, `scores`.

## How to get to it (user POV)
After a run: `uv run s1evals query "select trace_id from trace_labels where task_type = 'bugfix'" --include-unadmitted`.

## Driving it with the CLI
End state: JSON rows. Without `--include-unadmitted` only admitted rubrics become columns, as the design doc requires.

## Gotchas
Uses the latest run unless `--run-id` is given.
