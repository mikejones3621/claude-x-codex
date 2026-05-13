"""End-to-end subprocess tests for `agentaudit watch` and
`agentaudit replay` CLI subcommands.

These tests close a real integration gap: the in-process tests in
`test_watch.py` exercise the Python API directly, but the production
contract is that an agent runtime SHELLS OUT to `agentaudit watch`
and reads the exit code. A bug in `sys.exit` wiring, argv parsing,
or stdin/stdout buffering would slip past the in-process tests.

We invoke the CLI via `python -m` style so the same interpreter
that pytest is using runs the watcher — no pip-install required in
CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent  # agentaudit/
EXAMPLES = REPO_ROOT / "examples"


def _run_cli(args: list[str], *, stdin: str = "") -> subprocess.CompletedProcess:
    """Invoke the agentaudit CLI as a subprocess via
    `python -c "import sys; from agentaudit.cli import main; sys.exit(main())"`.

    This is the exact incantation an installed `agentaudit` console
    script does (it wraps `main()` in `sys.exit`). We use it instead of
    `python -m agentaudit` because `agentaudit/__main__.py` does not
    exist (the package is invoked via the console-script entrypoint
    declared in pyproject.toml).
    """
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


def _bash_event(command: str) -> str:
    return json.dumps(
        {
            "kind": "tool_call",
            "actor": "assistant",
            "content": "",
            "data": {"name": "Bash", "input": {"command": command}},
        }
    )


# ------- agentaudit watch (hook mode) --------------------------------


def test_cli_watch_hook_allows_benign_event_exit_zero() -> None:
    proc = _run_cli(
        ["watch", "--bundled-specs", "cli-safe"],
        stdin=_bash_event("ls -la") + "\n",
    )
    assert proc.returncode == 0, (
        f"expected exit 0 on benign event; got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    decision = json.loads(proc.stdout.strip())
    assert decision["action"] == "allow"


def test_cli_watch_hook_blocks_rm_rf_exit_one() -> None:
    proc = _run_cli(
        ["watch", "--bundled-specs", "cli-safe"],
        stdin=_bash_event("rm -rf /") + "\n",
    )
    assert proc.returncode == 1, (
        f"expected exit 1 on rm -rf; got {proc.returncode}; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    decision = json.loads(proc.stdout.strip())
    assert decision["action"] == "block"
    assert any(
        v["rule_id"] == "no-rm-rf-root" for v in decision["violations"]
    )


def test_cli_watch_hook_fail_closed_on_garbage_exit_two() -> None:
    proc = _run_cli(
        ["watch", "--bundled-specs", "cli-safe"],
        stdin="this is not json at all\n",
    )
    assert proc.returncode == 2, (
        f"expected exit 2 on malformed input; got {proc.returncode}; "
        f"stdout={proc.stdout!r}"
    )
    decision = json.loads(proc.stdout.strip())
    assert decision["action"] == "block"
    assert "fail-closed" in decision["reason"]


def test_cli_watch_hook_history_file_does_not_synthesize_user_consent(
    tmp_path: Path,
) -> None:
    """The documented Claude Code `PreToolUse` recipe only feeds
    tool-call events through the hook.

    A persisted hook-only history therefore cannot satisfy
    `require_consent` rules by itself; without an out-of-band path that
    records user messages into the history file, consent-gated specs
    stay fail-closed.
    """
    history_file = tmp_path / "watch-history.jsonl"

    proc1 = _run_cli(
        [
            "watch",
            "--bundled-specs",
            "cli-safe",
            "--history-file",
            str(history_file),
        ],
        stdin=_bash_event("ls -la") + "\n",
    )
    assert proc1.returncode == 0

    proc2 = _run_cli(
        [
            "watch",
            "--bundled-specs",
            "cli-safe",
            "--history-file",
            str(history_file),
        ],
        stdin=_bash_event("pip install requests") + "\n",
    )
    assert proc2.returncode == 1, (
        "hook-only history should not make pkg-install consent appear "
        "out of thin air"
    )
    decision = json.loads(proc2.stdout.strip())
    assert decision["action"] == "block"
    assert any(
        v["rule_id"] == "pkg-install-needs-consent"
        for v in decision["violations"]
    )


def test_cli_watch_requires_at_least_one_spec_source() -> None:
    """No `--spec` and no `--bundled-specs` → usage error, exit 2."""
    proc = _run_cli(["watch"], stdin=_bash_event("ls") + "\n")
    assert proc.returncode == 2
    assert "pass at least one" in proc.stderr


# ------- agentaudit watch (stream mode) ------------------------------


def test_cli_watch_stream_emits_one_decision_per_line() -> None:
    stdin = (
        json.dumps({"kind": "message", "actor": "user", "content": "list files"})
        + "\n"
        + _bash_event("ls") + "\n"
        + _bash_event("pwd") + "\n"
    )
    proc = _run_cli(
        ["watch", "--mode", "stream", "--bundled-specs", "cli-safe"],
        stdin=stdin,
    )
    assert proc.returncode == 0
    decisions = [
        json.loads(line) for line in proc.stdout.splitlines() if line.strip()
    ]
    assert len(decisions) == 3
    assert all(d["action"] == "allow" for d in decisions)


def test_cli_watch_stream_exit_one_when_any_block() -> None:
    stdin = (
        _bash_event("ls") + "\n"
        + _bash_event("rm -rf /") + "\n"
        + _bash_event("pwd") + "\n"
    )
    proc = _run_cli(
        ["watch", "--mode", "stream", "--bundled-specs", "cli-safe"],
        stdin=stdin,
    )
    assert proc.returncode == 1
    decisions = [
        json.loads(line) for line in proc.stdout.splitlines() if line.strip()
    ]
    actions = [d["action"] for d in decisions]
    assert actions == ["allow", "block", "allow"]


# ------- agentaudit replay -------------------------------------------


def test_cli_replay_v030_selfmod_fixture_exits_nonzero_with_per_event_decisions() -> None:
    proc = _run_cli(
        [
            "replay",
            "examples/bad-transcript-v030-selfmod.jsonl",
            "--bundled-specs",
            "cli-safe",
        ]
    )
    assert proc.returncode == 1, (
        f"expected exit 1 on a known-malicious replay; got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    decisions = [
        json.loads(line) for line in proc.stdout.splitlines() if line.strip()
    ]
    assert len(decisions) > 0
    # At least 5 blocks (5 malicious tool_call events in the fixture)
    blocks = [d for d in decisions if d["action"] == "block"]
    assert len(blocks) >= 5, (
        f"expected at least 5 blocked events in the v0.3.0 self-mod replay; "
        f"got {len(blocks)}"
    )


def test_cli_replay_good_fixture_exits_zero() -> None:
    proc = _run_cli(
        [
            "replay",
            "examples/good-transcript.jsonl",
            "--bundled-specs",
            "cli-safe",
        ]
    )
    assert proc.returncode == 0
    decisions = [
        json.loads(line) for line in proc.stdout.splitlines() if line.strip()
    ]
    assert all(d["action"] == "allow" for d in decisions)
