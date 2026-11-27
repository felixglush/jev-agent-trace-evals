# s1evals

System One evals on coding-agent traces. Read README.md for the layout; the design doc lives in project memory.

- Run everything through uv: `uv run s1evals ...`, `uv run pytest -q`, `uv run ruff check src tests && uv run ruff format src tests`.
- This repo is public and SWE-chat is gated: never commit trace text. `data/` holds the store and payloads and is gitignored; `experiments/<run_id>/` holds ids, labels and metrics only.
- Use the TypeSafe skill (`typesafe@typesafe-ai`) when touching `judges/jev.py` or rubric wording. Question wording lives only in `rubrics/*.yaml`.
- Changing a rubric's question, labels or extractor means bumping its `version`.
- To prove a change works, follow `.claude/skills/verify-s1evals/SKILL.md`.
