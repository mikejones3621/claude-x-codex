"""Tests for agentaudit CLI entrypoints."""

from __future__ import annotations

from agentaudit.cli import main


def test_list_adapters_prints_registered_adapters(capsys) -> None:
    rc = main(["list-adapters"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "anthropic_messages" in out
    assert "claude_code" in out
    assert "openai_agents" in out
