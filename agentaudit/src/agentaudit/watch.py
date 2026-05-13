"""Live-blocking mode for agentaudit.

`agentaudit watch` turns the post-hoc transcript checker into a
real-time guard: an agent runtime invokes the watcher with each tool
call (or message) as it happens; the watcher evaluates the event in
the context of the transcript so far and returns an
allow/block decision.

Two modes are supported:

  * **Hook mode** (`--mode hook`, default). The watcher reads ONE
    JSON event from stdin, decides, prints the decision on stdout,
    and exits 0 on allow / 1 on block. Designed to plug into per-
    tool-call hooks (Claude Code's `.claude/hooks/`, OpenAI Agents
    `before_handoff`, etc.). State is persisted between invocations
    via a `--history-file` JSONL path.

  * **Stream mode** (`--mode stream`). The watcher reads line-
    delimited JSON events from stdin forever, decides on each, and
    writes line-delimited decisions on stdout. State lives in memory
    for the lifetime of the process. Exits 0 if stdin closes with no
    blocks emitted, 1 if any block was emitted. Designed for sidecar
    deployments where the runtime emits a continuous tool-call
    stream over a pipe.

The decision is structured so blocking is *fail-closed*: ambiguous
input, malformed JSON, or an internal error all produce a block
decision rather than silently allowing the event through.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, TextIO

from agentaudit.checker import Violation, check
from agentaudit.schema import Event, Transcript
from agentaudit.spec import Spec


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class Decision:
    """The watcher's verdict on a single event."""

    action: str  # "allow" | "block"
    event_index: int
    violations: list[Violation] = field(default_factory=list)
    reason: str = ""  # human-readable summary

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "event_index": self.event_index,
            "reason": self.reason,
            "violations": [v.to_dict() for v in self.violations],
        }


def evaluate_event(
    history: list[Event],
    new_event: Event,
    specs: Iterable[Spec],
    *,
    block_severity: str = "high",
) -> Decision:
    """Decide whether `new_event` should be allowed given `history`.

    Runs every rule in `specs` against the transcript formed by
    appending `new_event` to `history`. Only violations whose
    `event_index` points at the new event factor into the
    allow/block decision (since prior events were already decided in
    earlier invocations). Block if any of those violations meet or
    exceed `block_severity`.
    """
    full = Transcript(events=history + [new_event])
    new_event_idx = len(history)

    all_violations: list[Violation] = []
    for spec in specs:
        all_violations.extend(check(full, spec))

    new_violations = [v for v in all_violations if v.event_index == new_event_idx]
    new_violations.sort(key=lambda v: (-v.severity_rank, v.rule_id))

    min_rank = SEVERITY_RANK[block_severity.lower()]
    blocking = [
        v for v in new_violations
        if SEVERITY_RANK.get(v.severity.lower(), 2) >= min_rank
    ]

    if blocking:
        ids = ", ".join(sorted({v.rule_id for v in blocking}))
        return Decision(
            action="block",
            event_index=new_event_idx,
            violations=new_violations,
            reason=f"blocked by {len(blocking)} rule(s) at or above {block_severity}: {ids}",
        )
    return Decision(
        action="allow",
        event_index=new_event_idx,
        violations=new_violations,
        reason="no blocking violations" if not new_violations else (
            f"{len(new_violations)} sub-threshold violation(s) recorded"
        ),
    )


def read_history(history_file: Path | None) -> list[Event]:
    """Read prior events from a JSONL history file (one Event per line).

    Returns an empty list if `history_file` is None or the file does
    not yet exist.
    """
    if history_file is None or not history_file.exists():
        return []
    events: list[Event] = []
    for lineno, line in enumerate(
        history_file.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{history_file}:{lineno}: invalid JSON in history: {exc}"
            ) from exc
        events.append(Event.from_dict(raw))
    return events


def append_history(history_file: Path, event: Event) -> None:
    """Append a single event to the history JSONL file."""
    history_file.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.to_dict(), sort_keys=True)
    with history_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def append_log(log_file: Path, decision: Decision) -> None:
    """Append a decision to the violation log file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(decision.to_dict(), sort_keys=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _parse_event(raw_line: str) -> Event:
    """Parse one line of stdin into an Event, raising on malformed input."""
    raw_line = raw_line.strip()
    if not raw_line:
        raise ValueError("empty input")
    try:
        raw = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("event must be a JSON object")
    return Event.from_dict(raw)


def run_hook_mode(
    stdin: TextIO,
    stdout: TextIO,
    specs: list[Spec],
    *,
    history_file: Path | None = None,
    log_file: Path | None = None,
    block_severity: str = "high",
    persist_blocked_events: bool = False,
) -> int:
    """Hook-mode entry point: one event in, one decision out.

    Returns the exit code (0 = allow, 1 = block, 2 = malformed input).
    Fail-closed: any error reading or parsing input produces a block.
    """
    line = stdin.read()
    try:
        event = _parse_event(line)
    except ValueError as exc:
        decision = Decision(
            action="block",
            event_index=-1,
            reason=f"refusing to allow malformed input (fail-closed): {exc}",
        )
        stdout.write(json.dumps(decision.to_dict()) + "\n")
        if log_file is not None:
            append_log(log_file, decision)
        return 2

    history = read_history(history_file)
    decision = evaluate_event(
        history, event, specs, block_severity=block_severity
    )
    stdout.write(json.dumps(decision.to_dict()) + "\n")
    if log_file is not None:
        append_log(log_file, decision)
    if history_file is not None:
        if decision.action == "allow" or persist_blocked_events:
            append_history(history_file, event)
    return 0 if decision.action == "allow" else 1


def run_stream_mode(
    stdin: TextIO,
    stdout: TextIO,
    specs: list[Spec],
    *,
    log_file: Path | None = None,
    block_severity: str = "high",
    persist_blocked_events: bool = False,
) -> int:
    """Stream-mode entry point: many events in, many decisions out.

    Returns 0 if stdin closed cleanly with no blocks emitted, 1 if at
    least one block was emitted, 2 if any input line was malformed
    (fail-closed: malformed lines still emit block decisions).
    """
    history: list[Event] = []
    any_block = False
    any_malformed = False
    for line in stdin:
        if not line.strip():
            continue
        try:
            event = _parse_event(line)
        except ValueError as exc:
            decision = Decision(
                action="block",
                event_index=len(history),
                reason=f"refusing to allow malformed input (fail-closed): {exc}",
            )
            stdout.write(json.dumps(decision.to_dict()) + "\n")
            stdout.flush()
            if log_file is not None:
                append_log(log_file, decision)
            any_block = True
            any_malformed = True
            continue

        decision = evaluate_event(
            history, event, specs, block_severity=block_severity
        )
        stdout.write(json.dumps(decision.to_dict()) + "\n")
        stdout.flush()
        if log_file is not None:
            append_log(log_file, decision)
        if decision.action == "allow" or persist_blocked_events:
            history.append(event)
        if decision.action == "block":
            any_block = True
    if any_malformed:
        return 2
    return 1 if any_block else 0
