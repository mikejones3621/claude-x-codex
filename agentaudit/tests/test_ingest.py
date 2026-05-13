"""Tests for `agentaudit.watch.run_ingest` and the corresponding
`agentaudit ingest` CLI subcommand.

This is the second-ingestion-path closure: by writing user-message
events into the same history file that `agentaudit watch` reads,
`require_consent` rules finally clear on hook deployments where the
PreToolUse hook only ever sees tool calls.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentaudit import (
    Event,
    EventKind,
    load_spec,
    read_history,
    run_hook_mode,
    run_ingest,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS = REPO_ROOT / "specs"


# ------- run_ingest in-process unit tests ---------------------------


def test_ingest_bare_text_wraps_as_user_message(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    rc = run_ingest(io.StringIO("yes, install it"), history)
    assert rc == 0
    events = read_history(history)
    assert len(events) == 1
    assert events[0].kind == EventKind.MESSAGE
    assert events[0].actor == "user"
    assert events[0].content == "yes, install it"


def test_ingest_json_with_prompt_field_unwraps(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    rc = run_ingest(
        io.StringIO(json.dumps({"prompt": "yes, install it"})),
        history,
    )
    assert rc == 0
    events = read_history(history)
    assert events[0].content == "yes, install it"


def test_ingest_json_with_text_field_unwraps(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    rc = run_ingest(
        io.StringIO(json.dumps({"text": "go ahead"})),
        history,
    )
    assert rc == 0
    assert read_history(history)[0].content == "go ahead"


def test_ingest_full_event_recorded_verbatim(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    full = {
        "kind": "message",
        "actor": "user",
        "content": "yes, install it",
        "id": "msg-42",
    }
    rc = run_ingest(io.StringIO(json.dumps(full)), history)
    assert rc == 0
    events = read_history(history)
    assert events[0].id == "msg-42"
    assert events[0].content == "yes, install it"


def test_ingest_empty_stdin_returns_two(tmp_path: Path) -> None:
    """Fail-closed: don't silently record an empty event."""
    history = tmp_path / "h.jsonl"
    rc = run_ingest(io.StringIO(""), history)
    assert rc == 2
    assert not history.exists()


def test_ingest_custom_actor_for_multi_agent_ingest(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    rc = run_ingest(
        io.StringIO("plan: do X then Y"),
        history,
        actor="agent:planner",
    )
    assert rc == 0
    events = read_history(history)
    assert events[0].actor == "agent:planner"


def test_ingest_fallback_serializes_unknown_dict(tmp_path: Path) -> None:
    """An object without any prompt-like field still survives — we
    fall back to JSON-serializing it so we never lose input."""
    history = tmp_path / "h.jsonl"
    weird = {"some_other_key": "user prompt was here"}
    rc = run_ingest(io.StringIO(json.dumps(weird)), history)
    assert rc == 0
    events = read_history(history)
    assert events[0].kind == EventKind.MESSAGE
    # Content should be the JSON serialization of the original object.
    assert "some_other_key" in events[0].content


# ------- end-to-end closure: ingest then watch ----------------------


def test_ingest_then_watch_consent_path_clears_pkg_install(tmp_path: Path) -> None:
    """The headline closure test for the gap Codex named:
    if we ingest a user-consent message into history, the subsequent
    watch hook for a pkg-install ALLOWS instead of fail-closed-blocking.

    Without this closure, the bare PreToolUse recipe would block
    `pip install requests` even after the user said "yes, install it"
    in chat.
    """
    spec = load_spec(SPECS / "no-pkg-install-without-confirm.md")
    history = tmp_path / "h.jsonl"

    # Step 1: user-prompt hook fires with the user's consent message.
    rc1 = run_ingest(io.StringIO("yes, install it"), history)
    assert rc1 == 0
    assert len(read_history(history)) == 1

    # Step 2: pre-tool-use hook fires with the pkg-install tool call.
    tool_call_line = json.dumps(
        {
            "kind": "tool_call",
            "actor": "assistant",
            "content": "",
            "data": {"name": "Bash", "input": {"command": "pip install requests"}},
        }
    )
    stdin = io.StringIO(tool_call_line + "\n")
    stdout = io.StringIO()
    rc2 = run_hook_mode(stdin, stdout, [spec], history_file=history)
    assert rc2 == 0, (
        "with user-consent ingested into history, pkg-install must allow; "
        f"stdout={stdout.getvalue()!r}"
    )
    decision = json.loads(stdout.getvalue())
    assert decision["action"] == "allow"

    # History now has both events (consent + the allowed tool call).
    persisted = read_history(history)
    assert len(persisted) == 2
    assert persisted[0].actor == "user"
    assert persisted[1].kind == EventKind.TOOL_CALL


def test_consent_path_does_not_synthesize_unrelated_consent(tmp_path: Path) -> None:
    """If the user said something that's NOT a consent phrase, the
    pkg-install rule must still block. Belt-and-suspenders on the
    closure: just having ANY user message in history isn't enough —
    the message must match the consent_phrases."""
    spec = load_spec(SPECS / "no-pkg-install-without-confirm.md")
    history = tmp_path / "h.jsonl"

    rc1 = run_ingest(io.StringIO("set up the project"), history)
    assert rc1 == 0

    tool_call_line = json.dumps(
        {
            "kind": "tool_call",
            "actor": "assistant",
            "content": "",
            "data": {"name": "Bash", "input": {"command": "pip install requests"}},
        }
    )
    stdin = io.StringIO(tool_call_line + "\n")
    stdout = io.StringIO()
    rc2 = run_hook_mode(stdin, stdout, [spec], history_file=history)
    assert rc2 == 1, (
        "non-consent user message must NOT clear the pkg-install gate"
    )


# ------- subprocess test: full CLI contract ------------------------


def _run_cli(args: list[str], *, stdin: str = "") -> subprocess.CompletedProcess:
    env = os.environ.copy()
    src_root = REPO_ROOT / "src"
    vendor = REPO_ROOT / ".pytest_vendor"
    parts = [str(src_root)]
    if vendor.exists():
        parts.append(str(vendor))
    existing = env.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from agentaudit.cli import main; sys.exit(main())",
            *args,
        ],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=30,
    )


def test_cli_ingest_then_watch_closes_the_consent_gap(tmp_path: Path) -> None:
    """End-to-end through the actual CLI: simulates the dual-hook
    deployment (UserPromptSubmit + PreToolUse) that Codex named as the
    missing path. This is the artifact-level claim that the gap is
    closed."""
    history = tmp_path / "watch-history.jsonl"

    # Step 1: the user-prompt hook records consent.
    proc1 = _run_cli(
        ["ingest", "--history-file", str(history), "--actor", "user"],
        stdin="yes, install it",
    )
    assert proc1.returncode == 0, (
        f"ingest must succeed; stderr={proc1.stderr!r}"
    )

    # Step 2: the pre-tool-use hook evaluates the pkg-install — should
    # ALLOW because the prior step recorded user consent into history.
    tool_call_event = json.dumps(
        {
            "kind": "tool_call",
            "actor": "assistant",
            "content": "",
            "data": {"name": "Bash", "input": {"command": "pip install requests"}},
        }
    )
    proc2 = _run_cli(
        [
            "watch",
            "--bundled-specs",
            "cli-safe",
            "--history-file",
            str(history),
        ],
        stdin=tool_call_event + "\n",
    )
    assert proc2.returncode == 0, (
        "after CLI ingest of consent, CLI watch must allow the pkg-install; "
        f"stdout={proc2.stdout!r}; stderr={proc2.stderr!r}"
    )
    decision = json.loads(proc2.stdout.strip())
    assert decision["action"] == "allow"


def test_cli_ingest_empty_stdin_errors(tmp_path: Path) -> None:
    history = tmp_path / "h.jsonl"
    proc = _run_cli(
        ["ingest", "--history-file", str(history)],
        stdin="",
    )
    assert proc.returncode == 2
    assert "empty stdin" in proc.stderr
