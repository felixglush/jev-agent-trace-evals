---
name: verify-s1evals
description: Drive the s1evals CLI and the annotation web app the way a user does, to prove a change works on real surfaces (trace loading, slices, Jev and Claude judges, experiment logs, annotation feedback). Use after changing anything under src/s1evals, rubrics/, or the annotate app.
---

# Verify s1evals

Two user surfaces: the `s1evals` CLI and the annotation app (`s1evals annotate`, FastAPI + one page). Everything runs from the repo root with `uv`. Verification uses its own DuckDB file, so it never touches `data/s1evals.duckdb`.

## Launch

```bash
export S1EVALS_DB=/tmp/s1verify/db.duckdb      # isolated store; delete to start clean
uv sync
uv run s1evals load snapshot tests/fixtures/*.json   # two synthetic traces, ready in <1s
```

Ready when `uv run s1evals traces` lists `fx_cleanup` and `fx_retry`.

Annotation app, in the background on a free port:

```bash
uv run s1evals annotate --port 8799 --author verifier > /tmp/s1verify/app.log 2>&1 &
echo $! > /tmp/s1verify/app.pid
```

Ready when `curl -s localhost:8799/api/meta` returns JSON. Two app instances can run side by side on different ports and `S1EVALS_DB` files.

## Doctor

```bash
uv run s1evals rubrics check | tail -1      # "12 rubrics valid"
uv run s1evals traces                       # store readable, traces loaded
curl -s localhost:8799/api/meta             # app up, author + runs listed
uv run pytest -q                            # unit + API tests (live Jev test skipped unless S1EVALS_LIVE=1)
```

Jev needs network access to `api.typesafe.ai` (the cloud sandbox proxy injects the key; locally set `TYPESAFE_API_KEY`). Claude judges need the `claude` CLI on PATH. SWE-chat needs Hugging Face access to the gated dataset (`HF_TOKEN`).

## Drive

CLI (see `features/` for each journey):

```bash
uv run s1evals slice fx_retry user_correction                # deterministic slice
uv run s1evals jev fx_retry user_correction                  # one live Jev call, prints request + verdict
uv run s1evals experiment run --run-id verify-fixtures       # all judges, writes experiments/verify-fixtures/
uv run s1evals --db $S1EVALS_DB query "select * from trace_labels" --include-unadmitted
S1EVALS_SNAPSHOT=tests/fixtures/fx_cleanup.json uv run s1evals trace overview   # the slow judge's tools
```

Annotation app, scripted with the preinstalled Playwright:

```bash
NODE_PATH=$(npm root -g) node .claude/skills/verify-s1evals/scripts/drive-annotate.cjs \
  http://127.0.0.1:8799 fx_cleanup user_correction /tmp/s1verify/shots
```

It opens the trace, focuses the rubric card (highlights its evidence), jumps to an evidence event, saves a label, a comment and a trace note, reloads, and exits 0 only if all three persisted and the page logged no errors. Stable handles: `#card-<rubric_id>`, `#card-<rubric_id> .fb select`, `.fb textarea`, `#note`, `#ev-<seq>`.

## Evidence

- CLI: the command, its stdout, and the files it wrote (`experiments/<run_id>/REPORT.md`, `metrics.json`, `verdicts.jsonl`).
- App: `/tmp/s1verify/shots/{1-trace,2-focused,3-after-reload}.png` plus the script's JSON line. Also confirm the side effect in the store: `uv run python -c "from s1evals.store import Store; print(Store('$S1EVALS_DB').feedback())"`.
- A live judge run proves itself by cost and latency in `REPORT.md`; a judge that silently returned nothing shows up in `problems.jsonl`.

## Cleanup

```bash
kill $(cat /tmp/s1verify/app.pid)          # only the app this run started
rm -rf experiments/verify-fixtures /tmp/s1verify/db.duckdb
```

Keep `/tmp/s1verify/shots/` as the proof. Never commit `data/` or experiment runs made from fixtures.
