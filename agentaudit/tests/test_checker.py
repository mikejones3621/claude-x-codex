"""Tests for agentaudit core."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentaudit import (
    check,
    load_spec,
    load_transcript,
)
from agentaudit.adapters import load_with_adapter


REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "specs"
EXAMPLES = REPO / "examples"


def _check_all(transcript_path: Path) -> list:
    transcript = load_transcript(transcript_path)
    out = []
    for spec_file in sorted(SPECS.glob("*.md")):
        out.extend(check(transcript, load_spec(spec_file)))
    out.sort(key=lambda v: (-v.severity_rank, v.event_index, v.rule_id))
    return out


def test_good_transcript_passes_all_specs() -> None:
    violations = _check_all(EXAMPLES / "good-transcript.jsonl")
    assert violations == [], "expected no violations: " + ", ".join(
        f"{v.rule_id}@{v.event_index}" for v in violations
    )


def test_bad_transcript_catches_known_failures() -> None:
    violations = _check_all(EXAMPLES / "bad-transcript.jsonl")
    ids = {v.rule_id for v in violations}
    expected = {
        "no-rm-rf-root",
        "no-secret-in-output",
        "no-curl-to-unapproved-host",
        "no-piped-network-shell",
        "no-force-push-main",
        "no-ssn-in-output",
        "no-credit-card-in-output",
    }
    missing = expected - ids
    assert not missing, f"missed expected violations: {missing}"


def test_severity_sort_puts_critical_first() -> None:
    violations = _check_all(EXAMPLES / "bad-transcript.jsonl")
    ranks = [v.severity_rank for v in violations]
    assert ranks == sorted(ranks, reverse=True)


def test_unknown_rule_type_raises() -> None:
    from agentaudit.spec import parse_spec
    from agentaudit.schema import Transcript

    spec = parse_spec(
        "## bad-rule: bogus type\n\n```agentaudit\ntype = does_not_exist\n```\n"
    )
    with pytest.raises(ValueError, match="unknown rule type"):
        check(Transcript(events=[]), spec)


def test_claude_code_adapter_normalizes_blocks(tmp_path: Path) -> None:
    raw = (
        '{"type":"user","message":{"content":"hi"}}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"ok"},'
        '{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"ls"}}]}}\n'
        '{"type":"user","message":{"content":[{"type":"tool_result",'
        '"tool_use_id":"t1","content":"a\\nb"}]}}\n'
    )
    p = tmp_path / "claude_code.jsonl"
    p.write_text(raw, encoding="utf-8")
    t = load_with_adapter("claude_code", p)
    kinds = [e.kind.value for e in t.events]
    assert kinds == ["message", "message", "tool_call", "tool_result"]
    assert t.events[2].data["name"] == "Bash"
    assert t.events[3].content == "a\nb"


def test_openai_agents_adapter_function_call(tmp_path: Path) -> None:
    raw = (
        '[{"type":"message","role":"user","content":"hi"},'
        '{"type":"function_call","name":"shell","arguments":"{\\"cmd\\":\\"ls\\"}",'
        '"call_id":"c1"},'
        '{"type":"function_call_output","call_id":"c1","output":"out"}]'
    )
    p = tmp_path / "openai.json"
    p.write_text(raw, encoding="utf-8")
    t = load_with_adapter("openai_agents", p)
    assert [e.kind.value for e in t.events] == ["message", "tool_call", "tool_result"]
    assert t.events[1].data["name"] == "shell"
    assert t.events[1].data["input"] == {"cmd": "ls"}


def test_consent_rule_blocks_then_unblocks(tmp_path: Path) -> None:
    spec_md = (
        "## need-consent: ask first\n\n"
        "```agentaudit\n"
        "type = require_consent\n"
        "severity = high\n"
        'tool = "Bash"\n'
        'consent_phrases = ["yes, run it"]\n'
        "```\n"
    )
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(spec_md, encoding="utf-8")
    spec = load_spec(spec_path)

    blocked = (
        '{"kind":"message","actor":"user","content":"do it"}\n'
        '{"kind":"tool_call","actor":"assistant","content":"",'
        '"data":{"name":"Bash","input":{"command":"ls"}}}\n'
    )
    p1 = tmp_path / "blocked.jsonl"
    p1.write_text(blocked, encoding="utf-8")
    assert len(check(load_transcript(p1), spec)) == 1

    allowed = (
        '{"kind":"message","actor":"user","content":"yes, run it"}\n'
        '{"kind":"tool_call","actor":"assistant","content":"",'
        '"data":{"name":"Bash","input":{"command":"ls"}}}\n'
    )
    p2 = tmp_path / "allowed.jsonl"
    p2.write_text(allowed, encoding="utf-8")
    assert check(load_transcript(p2), spec) == []
