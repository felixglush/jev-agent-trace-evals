"""Judge routing as a truth table: fast path, code-decided, or one of the fallbacks.

admitted? -- no --> slow (not admitted)
   | yes
extract -> Decided --> code label
        -> Missing --> slow (extraction failed / no evidence)
        -> Evidence over budget --> slow (overflow)
        -> Evidence --> Jev -- error --> slow (fast judge error)
                            -- confidence < threshold --> slow (low confidence)
                            -- otherwise --> fast label
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from s1evals.domain import Decided, Evidence, JudgeName, Missing, SliceResult, Verdict
from s1evals.rubrics import Rubric


class Route(StrEnum):
    CODE = "code"
    FAST = "fast"
    NOT_ADMITTED = "fallback:not_admitted"
    MISSING = "fallback:missing_evidence"
    OVER_BUDGET = "fallback:over_budget"
    FAST_ERROR = "fallback:fast_error"
    LOW_CONFIDENCE = "fallback:low_confidence"

    @property
    def is_fallback(self) -> bool:
        return self.value.startswith("fallback:")


@dataclass(frozen=True)
class Decision:
    route: Route
    label: str | None  # None until the slow judge answers a fallback
    judge: JudgeName | None
    reason: str


def needs_fast_judge(rubric: Rubric, slice_result: SliceResult, enforce_admission: bool = True) -> bool:
    if enforce_admission and not rubric.admitted:
        return False
    return isinstance(slice_result, Evidence) and slice_result.tokens <= rubric.budget_tokens


def route(
    rubric: Rubric,
    slice_result: SliceResult,
    fast: Verdict | None = None,
    fast_error: str | None = None,
    enforce_admission: bool = True,
) -> Decision:
    if enforce_admission and not rubric.admitted:
        return Decision(Route.NOT_ADMITTED, None, None, f"{rubric.id} v{rubric.version} is not admitted")
    match slice_result:
        case Decided(label=label, reason=reason):
            return Decision(Route.CODE, label, JudgeName.CODE, reason)
        case Missing(reason=reason):
            return Decision(Route.MISSING, None, None, reason)
        case Evidence(tokens=tokens) if tokens > rubric.budget_tokens:
            return Decision(Route.OVER_BUDGET, None, None, f"slice is {tokens} tokens > {rubric.budget_tokens}")
    if fast_error is not None:
        return Decision(Route.FAST_ERROR, None, None, fast_error)
    if fast is None:
        raise ValueError("route() needs the fast verdict or its error for an in-budget slice")
    confidence = fast.confidence if fast.confidence is not None else 0.0
    if confidence < rubric.threshold:
        return Decision(Route.LOW_CONFIDENCE, None, None, f"confidence {confidence:.2f} < {rubric.threshold}")
    return Decision(Route.FAST, fast.label, JudgeName.JEV, f"confidence {confidence:.2f}")


def resolve(decision: Decision, slow: Verdict | None) -> Decision:
    """Fill a fallback decision with the slow judge's label."""
    if not decision.route.is_fallback or slow is None:
        return decision
    return Decision(decision.route, slow.label, slow.judge, decision.reason)
