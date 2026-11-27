"""Rubric definitions, loaded and validated from the top-level `rubrics/` folder.

A rubric is one narrow question with a fixed label set. Labels in `labels` are
offered to the model (their descriptions become Jev's criteria); `code_labels`
lists what the extractor may assign without a model, either a code-only label
(e.g. "n/a" when no destructive command ran) or a model label it can settle
(e.g. "no" when no tool failed). Changing the question, labels or extractor means
bumping `version`, which changes `judge_version` and leaves old scores intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from s1evals.paths import REPO_ROOT

DEFAULT_DIR = REPO_ROOT / "rubrics"


class Kind(StrEnum):
    CHOICE = "choice"  # pick one of N labels
    NOUL = "noul"  # yes/no statement; labels must be exactly {yes, no}


class Scope(StrEnum):
    TRACE = "trace"  # judged over the whole session
    ITEM = "item"  # judged on one target event the extractor picks


@dataclass(frozen=True)
class Rubric:
    id: str
    version: int
    source: str
    question: str
    kind: Kind
    scope: Scope
    labels: dict[str, str]
    code_labels: dict[str, str]
    extractor: str
    evidence: str
    budget_tokens: int
    threshold: float
    admitted: bool
    sufficiency_risk: str

    @property
    def all_labels(self) -> list[str]:
        return [*self.labels, *(k for k in self.code_labels if k not in self.labels)]

    def judge_version(self, judge: str, model: str) -> str:
        return f"{self.id}@v{self.version}/{judge}:{model}"


def parse(raw: dict, origin: str = "<dict>") -> Rubric:
    try:
        rubric = Rubric(
            id=raw["id"],
            version=int(raw["version"]),
            source=raw["source"],
            question=raw["question"].strip(),
            kind=Kind(raw.get("kind", "choice")),
            scope=Scope(raw.get("scope", "trace")),
            labels={str(k): str(v).strip() for k, v in raw["labels"].items()},
            code_labels={str(k): str(v).strip() for k, v in (raw.get("code_labels") or {}).items()},
            extractor=raw.get("extractor", raw["id"]),
            evidence=raw["evidence"].strip(),
            budget_tokens=int(raw.get("budget_tokens", 4000)),
            threshold=float(raw.get("threshold", 0.5)),
            admitted=bool(raw.get("admitted", False)),
            sufficiency_risk=raw.get("sufficiency_risk", "unknown"),
        )
    except (KeyError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid rubric {origin}: {exc}") from exc
    if rubric.kind is Kind.NOUL and set(rubric.labels) != {"yes", "no"}:
        raise ValueError(f"invalid rubric {origin}: a noul rubric needs labels exactly yes/no")
    if len(rubric.labels) < 2:
        raise ValueError(f"invalid rubric {origin}: needs at least two model labels")
    return rubric


def load(directory: Path = DEFAULT_DIR) -> dict[str, Rubric]:
    from s1evals.slices.extractors import REGISTRY

    rubrics: dict[str, Rubric] = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        rubric = parse(yaml.safe_load(path.read_text()), str(path))
        if rubric.id != path.stem:
            raise ValueError(f"rubric id {rubric.id!r} must match its file name {path.name}")
        if rubric.extractor not in REGISTRY:
            raise ValueError(f"rubric {rubric.id}: no extractor named {rubric.extractor!r}")
        rubrics[rubric.id] = rubric
    return rubrics
