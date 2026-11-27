"""Token estimates and truncation helpers shared by loaders and extractors."""

from __future__ import annotations

# Rough tokenizer-free estimate. Slice budgets are checked against this, and
# Jev's reported input_tokens are logged next to it for comparison.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def head(text: str, max_tokens: int) -> str:
    limit = max_tokens * CHARS_PER_TOKEN
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def tail(text: str, max_tokens: int) -> str:
    limit = max_tokens * CHARS_PER_TOKEN
    return text if len(text) <= limit else "[truncated]… " + text[-limit:]
