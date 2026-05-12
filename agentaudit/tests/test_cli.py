"""Tests for agentaudit CLI entrypoints."""

from __future__ import annotations

from pathlib import Path

from agentaudit.cli import main


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
