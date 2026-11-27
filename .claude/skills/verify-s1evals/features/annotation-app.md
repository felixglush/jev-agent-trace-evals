# Annotation app

## Sub-features
- Trace list with labelled counts; run selector.
- Per-rubric card: question, route, Jev probabilities, Claude slice and agent labels with explanations and evidence seqs, the slice itself, label definitions.
- Event timeline with role filters; focusing a card highlights its evidence; seq links jump to events.
- Feedback: human label + comment per rubric, a note per trace; saved to the `feedback` table.
- Review Jev tab (`/api/review`): every Jev answer in the run with confidence, the agent's and Claude-on-slice labels and your label; filters for rubric, disagreements and kept answers; rows open the trace with that card focused; j/k step through rows.

## How to get to it (user POV)
`uv run s1evals annotate`, open http://127.0.0.1:8765.

## Driving it with Playwright
`scripts/drive-annotate.cjs <url> fx_cleanup user_correction <out>`; exit 0 and `"ok": true` prove the save → reload round trip.

Review tab: select a run in `#run`, click `#tab-review`, pick a rubric in `#review-controls select`, click a `.rv` row and expect `#card-<rubric>.focus`.

## Gotchas
Without a scored run the cards show slices only. The author name comes from `--author` (default `$USER`); feedback is stored per author.
