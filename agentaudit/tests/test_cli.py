"""Tests for agentaudit CLI entrypoints."""

from __future__ import annotations

import json
from pathlib import Path

from agentaudit.cli import _auto_load, main


def test_list_adapters_prints_registered_adapters(capsys) -> None:
    rc = main(["list-adapters"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "anthropic_messages" in out
    assert "claude_code" in out
    assert "openai_agents" in out


def test_list_specs_prints_bundled_specs(capsys) -> None:
    rc = main(["list-specs"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "no-secret-leak.md" in out
    assert "openai-agents/tool-allowlist.md" in out


def test_list_specs_verbose_marks_judge_backed_specs(capsys) -> None:
    rc = main(["list-specs", "--verbose"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "no-secret-leak.md\tdeterministic" in out
    assert "openai-agents/prompt-injection-resistance.md\tjudge-backed" in out
    assert (
        "openai-agents/tool-allowlist.md\tdeterministic+deployment-specific"
        in out
    )


def test_list_specs_cli_safe_omits_judge_backed_specs(capsys) -> None:
    rc = main(["list-specs", "--cli-safe"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "openai-agents/prompt-injection-resistance.md" not in out
    assert "openai-agents/tool-allowlist.md" not in out
    assert "openai-agents/fabricated-system-messages.md" in out


def test_list_specs_deployment_specific_filters_to_policy_specs(capsys) -> None:
    rc = main(["list-specs", "--deployment-specific"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert out == ["openai-agents/tool-allowlist.md"]


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


def test_check_requires_spec_or_bundled_specs(capsys) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "good-transcript.jsonl"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "pass at least one `--spec` or choose `--bundled-specs`" in captured.err


def test_check_resolves_bundled_spec_relative_path(capsys) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "openai-agents-wrapped-good.json"),
            "--adapter",
            "openai_agents",
            "--spec",
            "openai-agents/tool-allowlist.md",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["summary"]["total"] == 0


def test_check_with_bundled_specs_cli_safe_runs_cleanly(capsys) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "openai-agents-wrapped-good.json"),
            "--adapter",
            "openai_agents",
            "--bundled-specs",
            "cli-safe",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["summary"]["total"] == 0


def test_check_with_bundled_specs_cli_safe_runs_cleanly_on_generic_fixture(
    capsys,
) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "good-transcript.jsonl"),
            "--bundled-specs",
            "cli-safe",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["summary"]["total"] == 0


def test_check_with_bundled_specs_all_hits_judge_boundary(capsys) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "openai-agents-wrapped-good.json"),
            "--adapter",
            "openai_agents",
            "--bundled-specs",
            "all",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "judge-backed rules are only supported via the Python API" in captured.err


def test_check_with_bundled_specs_deterministic_runs_deployment_specific_specs(
    capsys,
) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "openai-agents-wrapped-good.json"),
            "--adapter",
            "openai_agents",
            "--bundled-specs",
            "deterministic",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["summary"]["total"] == 0


def test_check_with_bundled_specs_deployment_specific_fails_on_openai_bad_fixture(
    capsys,
) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "openai-agents-bad.json"),
            "--adapter",
            "openai_agents",
            "--bundled-specs",
            "deployment-specific",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    payload = json.loads(captured.out)
    allowlist_hits = [
        violation
        for violation in payload["violations"]
        if violation["rule_id"] == "only-approved-tools"
    ]
    assert len(allowlist_hits) == 1
    assert allowlist_hits[0]["event_index"] == 3


def test_check_dedupes_explicit_spec_against_bundled_set(capsys) -> None:
    repo = Path(__file__).resolve().parent.parent
    rc = main(
        [
            "check",
            str(repo / "examples" / "bad-transcript.jsonl"),
            "--bundled-specs",
            "cli-safe",
            "--spec",
            "no-secret-leak.md",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    payload = json.loads(captured.out)
    secret_hits = [
        violation
        for violation in payload["violations"]
        if violation["rule_id"] == "no-secret-in-output"
    ]
    assert len(secret_hits) == 2
    assert {violation["event_index"] for violation in secret_hits} == {5, 6}


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
