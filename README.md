# System One evals on agent traces

Grade long coding-agent traces with a small, cheap classifier that reads only an extracted evidence slice, and fall back to an LLM agent judge when the slice can't be trusted. This reproduces Judgment Labs' [System One evals](https://www.judgmentlabs.ai/blogs/system-one-evals) on [SWE-chat](https://huggingface.co/datasets/SALT-NLP/SWE-chat), following the project design doc.

- **Fast judge:** TypeSafe's Jev (`jev-1.14.0`) answers one typed question per rubric over the slice.
- **Slow judge:** a Claude agent (headless Claude Code, Opus) reads the full trace through read-only tools.
- **Claude on the slice:** the blog's "LLM on preprocessed evidence" setup, also used as the Gate 1 sufficiency probe.

## Layout

The code follows the design doc's pipeline, one module per box:

```
rubrics/                    one YAML per rubric (question, labels, slice, budget, threshold, admitted)
src/s1evals/
  domain.py                 Event, Trace, slice outcomes (Evidence | Decided | Missing), Verdict
  store.py                  DuckDB: traces, events, slices, scores, feedback
  loaders/swechat.py        sample SWE-chat sessions, map `conversations` rows to events
  loaders/snapshot.py       common-schema JSON (fixtures, slow-judge snapshots)
  rubrics.py                load and validate rubrics/
  slices/extractors.py      extract(): one pure function per rubric
  judges/jev.py             fast judge (TypeSafe HTTP API)
  judges/claude.py          Claude on the slice, Claude agent on the full trace
  tracetools.py             get_turns / search / get_tool_result: the agent's only tools
  routing.py                fast path vs. fallback, as a truth table
  analysis.py, report.py    agreement, calibration, fallback rate, cost, Gate 1
  experiments.py            run judges, write experiments/<run_id>/
  index.py                  evals as indexes: trace_labels view
  annotate/                 annotation app (FastAPI + one page)
  cli/                      `s1evals` commands, one module per group
experiments/                experiment logs (ids, labels, metrics; no trace text)
tests/                      unit, API and CLI tests; fixtures/ holds two synthetic traces
.claude/skills/verify-s1evals/  how to drive the CLI and app to prove a change works
```

## Quick start

```bash
uv sync
uv run s1evals rubrics check
uv run s1evals load snapshot tests/fixtures/*.json        # or: load swechat --n 20 (needs HF access)
uv run s1evals slice fx_retry user_correction
uv run s1evals jev fx_retry user_correction               # one live Jev call
uv run s1evals experiment run --run-id my-run              # Jev + Claude slice + Claude agent
uv run s1evals annotate                                   # http://127.0.0.1:8765
uv run s1evals query "select * from trace_labels" --include-unadmitted
uv run pytest -q
```

Credentials: Jev reads `TYPESAFE_API_KEY` (the cloud sandbox's proxy injects it). Claude judges need the `claude` CLI signed in. SWE-chat is gated: accept the terms on Hugging Face and set `HF_TOKEN`.

## Routing

```
rubric admitted? -- no --> slow judge
extract slice -> decided by code (e.g. no shell calls -> n/a) --> code label
              -> missing evidence / extractor error --> slow judge
              -> over the token budget --> slow judge
              -> Jev -> error or confidence < threshold --> slow judge
                     -> otherwise --> fast label
```

A rubric is admitted after Gate 1 (one question, addressable, bounded, sufficient on ~20 traces) and Gate 2 (agreement within 3 points of the slow judge, calibration, fallback rate under 15%). Every rubric starts unadmitted; experiments run all judges on every pair and simulate routing, so the gates can be measured.
