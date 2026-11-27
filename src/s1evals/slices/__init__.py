"""Evidence slices: deterministic extraction plus the runtime guards from Gate 1."""

from __future__ import annotations

from s1evals.domain import Event, Evidence, Missing, SliceResult
from s1evals.rubrics import Rubric
from s1evals.slices.extractors import REGISTRY


def extract(rubric: Rubric, events: list[Event]) -> SliceResult:
    """Run the rubric's extractor. A crash is a Missing (route to slow judge),
    never an exception that kills a batch."""
    fn = REGISTRY[rubric.extractor]
    try:
        return fn(events)
    except Exception as exc:  # noqa: BLE001 - the guard is the point
        return Missing(f"extractor error: {type(exc).__name__}: {exc}")


def over_budget(rubric: Rubric, result: SliceResult) -> bool:
    return isinstance(result, Evidence) and result.tokens > rubric.budget_tokens
