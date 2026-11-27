"""Fast judge: TypeSafe's Jev answers typed questions about a rubric's slice.

Most rubrics send one question over the whole slice. A rubric with `jev_items`
sends one Noul per item instead (each item placed in its question), all in one
request, and code in judges/aggregate.py turns the answers into the label.

Request building and response parsing are pure functions so the exact payload
is testable and loggable; only `JevJudge.judge` touches the network.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import httpx

from s1evals.domain import Evidence, JudgeName, Verdict
from s1evals.judges import JudgeError
from s1evals.judges.aggregate import REGISTRY as AGGREGATES
from s1evals.rubrics import Kind, Rubric

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000
QUESTION_ID = "verdict"


def build_request(rubric: Rubric, evidence: Evidence, model: str = MODEL) -> dict:
    if rubric.jev_items:
        return build_item_request(rubric, evidence, model)
    if rubric.kind is Kind.NOUL:
        question = {
            "type": "noul",
            "instructions": rubric.question,
            "criteria": {"true": rubric.labels["yes"], "false": rubric.labels["no"]},
        }
    else:
        question = {"type": "choice", "instructions": rubric.question, "criteria": dict(rubric.labels)}
    return {"model": model, "state": evidence.state, "questions": {QUESTION_ID: question}}


def item_question_id(question_id: str, index: int) -> str:
    return f"{question_id}_{index}"


def build_item_request(rubric: Rubric, evidence: Evidence, model: str = MODEL) -> dict:
    spec = rubric.jev_items
    items = evidence.state.get(spec.items) or []
    if not items:
        raise JudgeError(f"{rubric.id}: slice has no {spec.items!r} to ask about")
    questions = {
        item_question_id(qid, i): {
            "type": "noul",
            "instructions": f"{q.instructions}\n\n{json.dumps(item, ensure_ascii=False, indent=1)}",
            "criteria": {"true": q.true, "false": q.false},
        }
        for i, item in enumerate(items)
        for qid, q in spec.questions.items()
    }
    state = {k: evidence.state[k] for k in spec.context if evidence.state.get(k) is not None}
    return {"model": model, "state": state, "questions": questions}


def _item_answers(rubric: Rubric, evidence: Evidence, answers: dict) -> list[dict[str, float]]:
    spec = rubric.jev_items
    n = len(evidence.state[spec.items])
    return [{qid: float(answers[item_question_id(qid, i)]["noul"]) for qid in spec.questions} for i in range(n)]


def parse_response(
    rubric: Rubric, trace_id: str, evidence: Evidence, body: dict, latency_s: float, model: str = MODEL
) -> Verdict:
    try:
        input_tokens = int(body.get("usage", {}).get("input_tokens", 0))
        if rubric.jev_items:
            items = _item_answers(rubric, evidence, body["answers"])
            label, probabilities, confidence = AGGREGATES[rubric.jev_items.aggregate](items)
        elif rubric.kind is Kind.NOUL:
            answer = body["answers"][QUESTION_ID]
            p = float(answer["noul"])
            probabilities = {"yes": p, "no": 1 - p}
            label = "yes" if p >= 0.5 else "no"
            # Distance from the coin-flip point: 0.5 threshold <=> p outside [0.25, 0.75].
            confidence = abs(2 * p - 1)
        else:
            answer = body["answers"][QUESTION_ID]
            probabilities = {k: float(v) for k, v in answer["probabilities"].items()}
            label = answer["choice"]
            confidence = float(answer["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise JudgeError(f"unexpected Jev response: {body!r}") from exc
    if label not in rubric.labels:
        raise JudgeError(f"Jev returned unknown label {label!r} for {rubric.id}")
    return Verdict(
        trace_id=trace_id,
        rubric_id=rubric.id,
        judge=JudgeName.JEV,
        label=label,
        confidence=confidence,
        probabilities=probabilities,
        evidence_ref=evidence.refs,
        judge_version=rubric.judge_version(JudgeName.JEV, body.get("model", model)),
        cost_usd=input_tokens * USD_PER_INPUT_TOKEN,
        latency_s=latency_s,
        input_tokens=input_tokens,
    )


@dataclass
class JevJudge:
    model: str = MODEL
    url: str = URL
    timeout_s: float = 60.0
    retries: int = 2
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=60.0))

    def judge(self, rubric: Rubric, trace_id: str, evidence: Evidence) -> tuple[Verdict, dict]:
        """Returns the verdict and the exact request payload sent."""
        payload = build_request(rubric, evidence, self.model)
        # The egress proxy injects the bearer token in the cloud sandbox; locally
        # set TYPESAFE_API_KEY.
        headers = {"Authorization": f"Bearer {os.environ.get('TYPESAFE_API_KEY', 'proxy-injected')}"}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            start = time.monotonic()
            try:
                resp = self.client.post(self.url, json=payload, headers=headers, timeout=self.timeout_s)
            except httpx.HTTPError as exc:
                last = exc
            else:
                if resp.status_code == 200:
                    try:
                        body = resp.json()
                    except ValueError as exc:
                        raise JudgeError(f"Jev returned non-JSON: {resp.text[:200]}") from exc
                    latency = time.monotonic() - start
                    return parse_response(rubric, trace_id, evidence, body, latency, self.model), payload
                last = JudgeError(f"Jev HTTP {resp.status_code}: {resp.text[:300]}")
                if resp.status_code < 500 and resp.status_code != 429:
                    break
            time.sleep(2**attempt)
        raise JudgeError(f"Jev call failed for {trace_id}/{rubric.id}: {last}")
