"""Tests for `agentaudit.watch.run_replay` — feed a stored transcript
through the live-blocking pipeline and assert decisions."""

from __future__ import annotations

import io
import json
from pathlib import Path

from agentaudit import (
    Event,
    EventKind,
    Transcript,
    load_spec,
    load_transcript,
    run_replay,
)


REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "specs"
EXAMPLES = REPO / "examples"


def test_replay_v030_selfmod_fixture_blocks_every_malicious_step() -> None:
    """Replay the canonical v0.3.0 self-mod fixture through the
    live-blocking pipeline; every malicious tool call must block."""
    specs = [
        load_spec(SPECS / "no-pkg-install-without-confirm.md"),
        load_spec(SPECS / "no-credential-store-write.md"),
        load_spec(SPECS / "no-runtime-config-write-without-confirm.md"),
        load_spec(SPECS / "no-instruction-file-write-without-confirm.md"),
    ]
    transcript = load_transcript(EXAMPLES / "bad-transcript-v030-selfmod.jsonl")
    stdout = io.StringIO()

    rc = run_replay(transcript, stdout, specs)
    assert rc == 1  # at least one block

    decisions = [
        json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()
    ]
    # 12 events in the fixture: 1 user msg + 5 tool_calls + 5 tool_results + 1 final assistant msg
    assert len(decisions) == len(transcript.events)

    # The 5 malicious tool_call events must all be blocks. Find them
    # by their kind in the source transcript.
    for i, event in enumerate(transcript.events):
        if event.kind == EventKind.TOOL_CALL:
            assert decisions[i]["action"] == "block", (
                f"expected event #{i} ({event.data.get('input', {}).get('command')}) "
                f"to be blocked; got {decisions[i]['action']}"
            )


def test_replay_clean_transcript_allows_everything() -> None:
    """A benign transcript replays as all-allow."""
    specs = [load_spec(SPECS / "no-shell-without-confirm.md")]
    transcript = load_transcript(EXAMPLES / "good-transcript.jsonl")
    stdout = io.StringIO()

    rc = run_replay(transcript, stdout, specs)
    assert rc == 0

    decisions = [
        json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()
    ]
    assert all(d["action"] == "allow" for d in decisions)


def test_replay_blocked_event_does_not_pollute_subsequent_history() -> None:
    """If event N blocks, event N+1 should be evaluated as if N never
    happened. This is the "watch contract": in production the runtime
    would have refused event N, so the subsequent agent state never
    sees it."""
    spec = load_spec(SPECS / "no-shell-without-confirm.md")
    transcript = Transcript(
        events=[
            Event(kind=EventKind.MESSAGE, actor="user", content="clean up"),
            Event(
                kind=EventKind.TOOL_CALL,
                actor="assistant",
                data={"name": "Bash", "input": {"command": "rm -rf /"}},
            ),  # blocked
            Event(
                kind=EventKind.TOOL_CALL,
                actor="assistant",
                data={"name": "Bash", "input": {"command": "ls -la"}},
            ),  # benign — should NOT inherit the blocked one
        ]
    )
    stdout = io.StringIO()

    rc = run_replay(transcript, stdout, [spec])
    assert rc == 1

    decisions = [
        json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()
    ]
    actions = [d["action"] for d in decisions]
    assert actions == ["allow", "block", "allow"]


def test_replay_uses_block_severity_threshold() -> None:
    """At block_severity=critical, the high-severity pkg-install rule
    should not block."""
    spec = load_spec(SPECS / "no-pkg-install-without-confirm.md")
    transcript = Transcript(
        events=[
            Event(kind=EventKind.MESSAGE, actor="user", content="set up the project"),
            Event(
                kind=EventKind.TOOL_CALL,
                actor="assistant",
                data={"name": "Bash", "input": {"command": "pip install requests"}},
            ),
        ]
    )
    stdout = io.StringIO()

    rc = run_replay(transcript, stdout, [spec], block_severity="critical")
    assert rc == 0  # high-sev doesn't block when threshold is critical

    decisions = [
        json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()
    ]
    # Both events allowed; second one still records the violation as
    # sub-threshold for visibility.
    assert decisions[1]["action"] == "allow"
    assert len(decisions[1]["violations"]) == 1


def test_replay_writes_log_file(tmp_path: Path) -> None:
    spec = load_spec(SPECS / "no-shell-without-confirm.md")
    log_file = tmp_path / "decisions.jsonl"
    transcript = Transcript(
        events=[
            Event(kind=EventKind.MESSAGE, actor="user", content="x"),
            Event(
                kind=EventKind.TOOL_CALL,
                actor="assistant",
                data={"name": "Bash", "input": {"command": "rm -rf /"}},
            ),
        ]
    )
    stdout = io.StringIO()

    run_replay(transcript, stdout, [spec], log_file=log_file)
    assert log_file.exists()
    logged = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(logged) == 2
    assert logged[1]["action"] == "block"
