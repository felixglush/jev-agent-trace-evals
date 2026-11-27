"""Turn per-item Jev answers into one trace label, in code.

A rubric with a `jev_items` block asks Jev one or more Noul questions about
each item of its slice (each failure, each follow-up message). The functions
here hold the decision logic that maps those per-item probabilities to the
rubric's label. They take the max over items rather than multiplying odds,
because answers about items of one session are far from independent, and a
product would turn many small probabilities into a confident "yes".

Each function returns (label, probabilities, confidence). Confidence is the
distance from the 0.5 boundary that decided the label, on the same 0-1 scale as
a single Noul's |2p - 1|, so the routing threshold means the same thing.
"""

from __future__ import annotations

from collections.abc import Callable

ItemAnswers = list[dict[str, float]]  # one {question_id: p(true)} per item
Aggregate = Callable[[ItemAnswers], tuple[str, dict[str, float], float]]

REGISTRY: dict[str, Aggregate] = {}


def aggregate(name: str) -> Callable[[Aggregate], Aggregate]:
    def register(fn: Aggregate) -> Aggregate:
        REGISTRY[name] = fn
        return fn

    return register


def _distance(p: float) -> float:
    return abs(2 * p - 1)


@aggregate("any_unresolved")
def any_unresolved(items: ItemAnswers) -> tuple[str, dict[str, float], float]:
    """yes when any item's `unresolved` Noul is true."""
    p = max(item["unresolved"] for item in items)
    return ("yes" if p >= 0.5 else "no"), {"yes": p, "no": 1 - p}, _distance(p)


@aggregate("correction_severity")
def correction_severity(items: ItemAnswers) -> tuple[str, dict[str, float], float]:
    """major when some follow-up both corrects and redirects the agent, minor
    when some follow-up corrects it, none otherwise."""
    p_any = max(item["corrects"] for item in items)
    p_major = max(min(item["corrects"], item["redirects"]) for item in items)
    probabilities = {"none": 1 - p_any, "minor": max(0.0, p_any - p_major), "major": p_major}
    if p_major >= 0.5:
        return "major", probabilities, _distance(p_major)
    if p_any >= 0.5:
        return "minor", probabilities, min(_distance(p_any), _distance(p_major))
    return "none", probabilities, _distance(p_any)
