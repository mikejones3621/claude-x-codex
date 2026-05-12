"""Tests for agentaudit.report rendering helpers."""

from __future__ import annotations

import json

from agentaudit.checker import Violation
from agentaudit.report import render_json


def test_render_json_empty_report_includes_summary() -> None:
    payload = json.loads(render_json([]))
    assert payload["ok"] is True
    assert payload["summary"]["total"] == 0
    assert payload["summary"]["by_severity"] == {}
    assert payload["violations"] == []


def test_render_json_populates_counts_and_violations() -> None:
    violations = [
        Violation(
            rule_id="r1",
            rule_name="critical thing",
            severity="critical",
            event_index=2,
            actor="assistant",
            evidence="boom",
        ),
        Violation(
            rule_id="r2",
            rule_name="high thing",
            severity="high",
            event_index=5,
            actor="tool",
            evidence="whoops",
        ),
        Violation(
            rule_id="r3",
            rule_name="high thing 2",
            severity="high",
            event_index=7,
            actor="tool",
            evidence="again",
        ),
    ]
    payload = json.loads(render_json(violations))
    assert payload["ok"] is False
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["by_severity"] == {"critical": 1, "high": 2}
    assert [v["rule_id"] for v in payload["violations"]] == ["r1", "r2", "r3"]
