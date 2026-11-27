"""Turn per-item Jev answers into one trace label, in code.

A rubric with a `jev_items` block asks Jev one or more Noul questions about
each item of its slice (each failure, each follow-up message). The functions
here hold the decision logic that maps those per-item probabilities to the
rubric's label. They take the max over items rather than multiplying odds,
because answers about items of one session are far from independent, and a
product would turn many small probabilities into a confident "yes".

An item counts only when its Noul is above YES (0.7), and the trace is "no"
only when every item is below NO (0.3), TypeSafe's suggested starting
thresholds. A deciding probability between them means the slice does not
settle the question: its confidence is under 0.5, so routing sends the pair to
the slow judge. Each function returns (label, probabilities, confidence).
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


YES, NO = 0.7, 0.3


def banded_confidence(p: float) -> float:
    """0.5 at the band edges, rising to 1 at p = 0 or 1, and below 0.5 inside
    the unsettled band (0 at p = 0.5)."""
    if p >= YES:
        return 0.5 + 0.5 * (p - YES) / (1 - YES)
    if p <= NO:
        return 0.5 + 0.5 * (NO - p) / NO
    return 0.5 * abs(p - 0.5) / (YES - 0.5)


@aggregate("any_unresolved")
def any_unresolved(items: ItemAnswers) -> tuple[str, dict[str, float], float]:
    """yes when any failure is clearly unresolved, no when all clearly are not."""
    p = max(item["unresolved"] for item in items)
    return ("yes" if p >= 0.5 else "no"), {"yes": p, "no": 1 - p}, banded_confidence(p)


@aggregate("correction_severity")
def correction_severity(items: ItemAnswers) -> tuple[str, dict[str, float], float]:
    """major when some follow-up both corrects and redirects the agent, minor
    when some follow-up corrects it, none otherwise."""
    p_any = max(item["corrects"] for item in items)
    p_major = max(min(item["corrects"], item["redirects"]) for item in items)
    probabilities = {"none": 1 - p_any, "minor": max(0.0, p_any - p_major), "major": p_major}
    if p_major >= 0.5:
        return "major", probabilities, banded_confidence(p_major)
    if p_any >= 0.5:
        return "minor", probabilities, min(banded_confidence(p_any), banded_confidence(p_major))
    return "none", probabilities, banded_confidence(p_any)
