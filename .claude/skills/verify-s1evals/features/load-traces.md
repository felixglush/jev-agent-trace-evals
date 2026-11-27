# Load traces

## Sub-features
- `s1evals load snapshot <json...>`: common-schema fixtures.
- `s1evals load swechat --n 20`: deterministic SWE-chat sample (>=100 tool calls, >=3 prompts, <=3 per repo).

## How to get to it (user POV)
Run the command; then `s1evals traces` lists what loaded.

## Driving it with the CLI
`uv run s1evals load snapshot tests/fixtures/*.json && uv run s1evals traces`. End state: two rows, `fx_cleanup` (17 events) and `fx_retry` (15 events). Reloading the same file keeps the counts (idempotent).

## Gotchas
SWE-chat is gated: without HF access every read returns 401. The loader drops metadata rows, so `n_events` is smaller than the dataset's turn count.
