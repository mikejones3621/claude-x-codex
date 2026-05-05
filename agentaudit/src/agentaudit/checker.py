"""Run a Spec against a Transcript and return Violations."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Iterable

from agentaudit import rules as _rules_pkg
from agentaudit.schema import Transcript
from agentaudit.spec import Rule, Spec


@dataclass
class Violation:
    rule_id: str
    rule_name: str
    severity: str
    event_index: int
    actor: str
    evidence: str
    rationale: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def severity_rank(self) -> int:
        return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(
            self.severity.lower(), 2
        )


@dataclass
class JudgeFinding:
    event_index: int
    evidence: str
    actor: str = "assistant"
    details: dict[str, Any] = field(default_factory=dict)
    severity: str | None = None


Judge = Callable[[Rule, Transcript], Iterable[Violation | JudgeFinding | dict[str, Any]]]


def check(
    transcript: Transcript, spec: Spec, *, judge: Judge | None = None
) -> list[Violation]:
    """Apply every rule in `spec` to `transcript` and collect violations."""
    found: list[Violation] = []
    for rule in spec.rules:
        if rule.type == "judge":
            found.extend(_run_judge(rule, transcript, judge))
            continue
        evaluator = _rules_pkg.get(rule.type)
        if evaluator is None:
            raise ValueError(
                f"unknown rule type {rule.type!r} in rule {rule.id!r}; "
                f"known: {_rules_pkg.known_types()}"
            )
        for v in evaluator(rule, transcript):
            found.append(v)
    found.sort(key=lambda v: (-v.severity_rank, v.event_index, v.rule_id))
    return found


def check_rule(
    rule: Rule, transcript: Transcript, *, judge: Judge | None = None
) -> list[Violation]:
    if rule.type == "judge":
        return _run_judge(rule, transcript, judge)
    evaluator = _rules_pkg.get(rule.type)
    if evaluator is None:
        raise ValueError(f"unknown rule type {rule.type!r}")
    return list(evaluator(rule, transcript))


def _run_judge(
    rule: Rule, transcript: Transcript, judge: Judge | None
) -> list[Violation]:
    if judge is None:
        raise ValueError("judge callable is required for rule type 'judge'")
    out: list[Violation] = []
    for raw in judge(rule, transcript):
        if isinstance(raw, Violation):
            out.append(raw)
            continue
        if isinstance(raw, JudgeFinding):
            payload = raw
        elif isinstance(raw, dict):
            payload = JudgeFinding(
                event_index=int(raw.get("event_index", -1)),
                actor=str(raw.get("actor", "assistant")),
                evidence=str(raw.get("evidence", "")),
                details=dict(raw.get("details", {}) or {}),
                severity=(
                    str(raw["severity"]) if raw.get("severity") is not None else None
                ),
            )
        else:
            raise TypeError(
                "judge must yield Violation, JudgeFinding, or dict-compatible findings"
            )
        out.append(
            Violation(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=payload.severity or rule.severity,
                event_index=payload.event_index,
                actor=payload.actor,
                evidence=payload.evidence,
                rationale=rule.rationale,
                details=payload.details,
            )
        )
    return out
