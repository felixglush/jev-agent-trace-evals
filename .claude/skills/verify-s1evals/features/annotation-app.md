# Annotation app

## Sub-features
- Trace list with labelled counts; run selector.
- Per-rubric card: question, route, Jev probabilities, Claude slice and agent labels with explanations and evidence seqs, the slice itself, label definitions.
- Event timeline with role filters; focusing a card highlights its evidence; seq links jump to events.
- Feedback: human label + comment per rubric, a note per trace; saved to the `feedback` table.

## How to get to it (user POV)
`uv run s1evals annotate`, open http://127.0.0.1:8765.

## Driving it with Playwright
`scripts/drive-annotate.cjs <url> fx_cleanup user_correction <out>`; exit 0 and `"ok": true` prove the save → reload round trip.

## Gotchas
Without a scored run the cards show slices only. The author name comes from `--author` (default `$USER`); feedback is stored per author.
