"""Tests for the Anthropic Messages API adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentaudit import check, load_spec
from agentaudit.adapters import load_with_adapter
from agentaudit.cli import _auto_load

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
SPECS = REPO / "specs"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_request_envelope_with_messages_array(tmp_path: Path) -> None:
    raw = (
        '{"messages": ['
        '{"role": "user", "content": "Hi"},'
        '{"role": "assistant", "content": ['
        '{"type": "text", "text": "Hello"},'
        '{"type": "tool_use", "id": "t1", "name": "search", "input": {"q": "x"}}'
        ']},'
        '{"role": "user", "content": ['
        '{"type": "tool_result", "tool_use_id": "t1", "content": "results"}'
        ']}'
        ']}'
    )
    p = _write(tmp_path, "req.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    kinds = [e.kind.value for e in t.events]
    assert kinds == ["message", "message", "tool_call", "tool_result"]
    assert t.events[0].actor == "user"
    assert t.events[1].actor == "assistant"
    assert t.events[2].data["name"] == "search"
    assert t.events[2].data["input"] == {"q": "x"}
    assert t.events[3].actor == "tool"
    assert t.events[3].content == "results"


def test_bare_list_of_messages(tmp_path: Path) -> None:
    raw = (
        '['
        '{"role": "user", "content": "Hi"},'
        '{"role": "assistant", "content": "Hello"}'
        ']'
    )
    p = _write(tmp_path, "bare.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert [e.kind.value for e in t.events] == ["message", "message"]
    assert t.events[0].content == "Hi"
    assert t.events[1].content == "Hello"


def test_response_envelope_single_assistant_turn(tmp_path: Path) -> None:
    raw = (
        '{"id": "msg_1", "role": "assistant", "content": ['
        '{"type": "text", "text": "Working on it."},'
        '{"type": "tool_use", "id": "t9", "name": "search", "input": {"q": "agent audit"}}'
        ']}'
    )
    p = _write(tmp_path, "resp.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert [e.kind.value for e in t.events] == ["message", "tool_call"]
    assert t.events[0].actor == "assistant"
    assert t.events[1].data["input"] == {"q": "agent audit"}


def test_jsonl_one_message_per_line(tmp_path: Path) -> None:
    raw = (
        '{"role": "user", "content": "Hi"}\n'
        '{"role": "assistant", "content": "Hello"}\n'
    )
    p = _write(tmp_path, "msgs.jsonl", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert [e.kind.value for e in t.events] == ["message", "message"]


def test_thinking_block_becomes_reasoning_event(tmp_path: Path) -> None:
    raw = (
        '[{"role": "assistant", "content": ['
        '{"type": "thinking", "thinking": "Let me think first."},'
        '{"type": "text", "text": "OK."}'
        ']}]'
    )
    p = _write(tmp_path, "think.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert [e.kind.value for e in t.events] == ["reasoning", "message"]
    assert t.events[0].content == "Let me think first."


def test_tool_result_string_content(tmp_path: Path) -> None:
    raw = (
        '[{"role": "user", "content": ['
        '{"type": "tool_result", "tool_use_id": "t2", "content": "raw string"}'
        ']}]'
    )
    p = _write(tmp_path, "tr-str.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert t.events[0].kind.value == "tool_result"
    assert t.events[0].content == "raw string"
    assert t.events[0].actor == "tool"


def test_tool_result_list_blocks(tmp_path: Path) -> None:
    raw = (
        '[{"role": "user", "content": ['
        '{"type": "tool_result", "tool_use_id": "t3", "content": ['
        '{"type": "text", "text": "line one"},'
        '{"type": "text", "text": "line two"}'
        ']}'
        ']}]'
    )
    p = _write(tmp_path, "tr-list.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert t.events[0].content == "line one\nline two"


def test_tool_result_is_error_flag_preserved(tmp_path: Path) -> None:
    raw = (
        '[{"role": "user", "content": ['
        '{"type": "tool_result", "tool_use_id": "t4", "is_error": true, "content": "boom"}'
        ']}]'
    )
    p = _write(tmp_path, "tr-err.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert t.events[0].data["is_error"] is True


def test_unknown_block_type_is_dropped_silently(tmp_path: Path) -> None:
    raw = (
        '[{"role": "assistant", "content": ['
        '{"type": "image", "source": {"type": "base64", "data": "..."}},'
        '{"type": "text", "text": "Here it is."}'
        ']}]'
    )
    p = _write(tmp_path, "img.json", raw)
    t = load_with_adapter("anthropic_messages", p)
    assert [e.kind.value for e in t.events] == ["message"]
    assert t.events[0].content == "Here it is."


def test_empty_input_yields_no_events(tmp_path: Path) -> None:
    p = _write(tmp_path, "empty.json", "")
    assert load_with_adapter("anthropic_messages", p).events == []


def test_bundled_good_fixture_passes_all_deterministic_specs() -> None:
    """The bundled `anthropic-messages-good.json` fixture is a clean
    customer-lookup transcript. It must pass every bundled deterministic
    spec including the OpenAI-shape allowlist (the fixture only uses
    `lookup_customer`, which is NOT on the allowlist — so we exclude
    that one spec here to keep the assertion meaningful).
    """
    transcript = load_with_adapter(
        "anthropic_messages", EXAMPLES / "anthropic-messages-good.json"
    )
    cross_lab_specs = [
        SPECS / "no-secret-leak.md",
        SPECS / "no-shell-without-confirm.md",
        SPECS / "no-network-exfil.md",
        SPECS / "no-pii-exfil.md",
        SPECS / "openai-agents" / "fabricated-system-messages.md",
    ]
    violations = []
    for spec_file in cross_lab_specs:
        violations.extend(check(transcript, load_spec(spec_file)))
    assert violations == [], (
        "expected no violations on clean Anthropic fixture: "
        + ", ".join(f"{v.rule_id}@{v.event_index}" for v in violations)
    )


def test_adapter_is_registered() -> None:
    """The adapter registers itself on import via the package __init__."""
    from agentaudit.adapters import list_adapters

    assert "anthropic_messages" in list_adapters()


def test_cli_auto_detects_anthropic_messages_fixture() -> None:
    """CLI auto-detection should pick the Anthropic adapter for the shipped
    worked example so users do not need `--adapter anthropic_messages` for
    the obvious path."""
    transcript = _auto_load(EXAMPLES / "anthropic-messages-good.json")
    kinds = [e.kind.value for e in transcript.events]
    assert kinds == ["message", "reasoning", "message", "tool_call", "tool_result", "message"]
    assert transcript.events[3].data["name"] == "lookup_customer"
