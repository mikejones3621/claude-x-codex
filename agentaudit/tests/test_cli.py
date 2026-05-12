"""Tests for agentaudit CLI entrypoints."""

from __future__ import annotations

from pathlib import Path

from agentaudit.cli import _auto_load, main


def test_list_adapters_prints_registered_adapters(capsys) -> None:
    rc = main(["list-adapters"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "anthropic_messages" in out
    assert "claude_code" in out
    assert "openai_agents" in out


def test_check_with_judge_backed_spec_fails_cleanly(capsys) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "openai-agents-bad.json"),
            "--adapter",
            "openai_agents",
            "--spec",
            str(repo / "specs" / "openai-agents" / "prompt-injection-resistance.md"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "judge-backed rules are only supported via the Python API" in captured.err


def test_auto_load_uses_content_not_just_messages_filename(tmp_path: Path) -> None:
    p = tmp_path / "messages-log.json"
    p.write_text(
        '[{"kind":"message","actor":"user","content":"hi"}]',
        encoding="utf-8",
    )
    transcript = _auto_load(p)
    assert len(transcript.events) == 1
    assert transcript.events[0].actor == "user"
    assert transcript.meta["source"] == str(p)


def test_auto_load_detects_anthropic_by_content_with_generic_filename(tmp_path: Path) -> None:
    p = tmp_path / "conversation.json"
    p.write_text(
        '{"messages":[{"role":"user","content":"hi"},{"role":"assistant","content":[{"type":"text","text":"ok"}]}]}',
        encoding="utf-8",
    )
    transcript = _auto_load(p)
    assert [e.kind.value for e in transcript.events] == ["message", "message"]
    assert transcript.events[1].actor == "assistant"


def test_auto_load_detects_openai_by_content_with_generic_filename(tmp_path: Path) -> None:
    p = tmp_path / "conversation.json"
    p.write_text(
        '{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok"}]}]}',
        encoding="utf-8",
    )
    transcript = _auto_load(p)
    assert [e.kind.value for e in transcript.events] == ["message"]
    assert transcript.events[0].actor == "assistant"
