"""Run a Spec against a Transcript and return Violations."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

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


def check(transcript: Transcript, spec: Spec) -> list[Violation]:
    """Apply every rule in `spec` to `transcript` and collect violations."""
    found: list[Violation] = []
    for rule in spec.rules:
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


def check_rule(rule: Rule, transcript: Transcript) -> list[Violation]:
    evaluator = _rules_pkg.get(rule.type)
    if evaluator is None:
        raise ValueError(f"unknown rule type {rule.type!r}")
    return list(evaluator(rule, transcript))
