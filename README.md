# System One evals on agent traces

Grade long coding-agent traces with a small, cheap classifier that reads only an extracted evidence slice, and fall back to an LLM agent judge when the slice can't be trusted. Reproduces Judgment Labs' [System One evals](https://www.judgmentlabs.ai/blogs/system-one-evals) on [SWE-chat](https://huggingface.co/datasets/SALT-NLP/SWE-chat).

```bash
uv sync
uv run s1evals load snapshot tests/fixtures/*.json   # or: load swechat --n 20 (needs HF access)
uv run s1evals traces
uv run s1evals --help
uv run pytest -q
```
