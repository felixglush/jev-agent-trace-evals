# Slices and rubrics

## Sub-features
- `s1evals rubrics check`: validates every `rubrics/*.yaml` and its extractor.
- `s1evals slice <trace> <rubric>`: prints Evidence / Decided / Missing.

## How to get to it (user POV)
Edit a rubric YAML, run `rubrics check`, then look at the slice for a trace.

## Driving it with the CLI
`uv run s1evals slice fx_retry user_correction` must show `follow_ups[0].user_follow_up` starting "No, I meant the multipart path". `uv run s1evals slice fx_retry destructive_without_confirmation` shows the requested `git checkout --`.

## Gotchas
YAML reads bare `yes`/`no` keys as booleans; noul labels must be quoted.
