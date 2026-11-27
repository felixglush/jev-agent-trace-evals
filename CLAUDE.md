# s1evals

System One evals on coding-agent traces. The design doc lives in project memory.

- Run everything through uv: `uv run s1evals ...`, `uv run pytest -q`, `uv run ruff check src tests && uv run ruff format src tests`.
- This repo is public and SWE-chat is gated: never commit trace text. `data/` holds the store and is gitignored.
