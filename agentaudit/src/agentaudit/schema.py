"""Canonical agent transcript schema.

A `Transcript` is an ordered sequence of `Event` records describing what
an LLM agent did over the course of a session. Adapters in
`agentaudit.adapters` convert lab-specific formats into this shape.

The schema is intentionally small. An event has:

  - kind: one of message, tool_call, tool_result, reasoning
  - actor: who produced it (user, assistant, system, tool name, etc.)
  - content: free-form text payload (always present)
  - data: structured payload for tool calls / results (optional)
  - timestamp: ISO-8601 UTC string (optional)
  - id: stable identifier within the transcript (optional)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class EventKind(str, Enum):
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REASONING = "reasoning"


@dataclass
class Event:
    kind: EventKind
    actor: str
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None
    id: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Event":
        kind = EventKind(raw["kind"])
        return cls(
            kind=kind,
            actor=str(raw.get("actor", "")),
            content=str(raw.get("content", "")),
            data=dict(raw.get("data", {}) or {}),
            timestamp=raw.get("timestamp"),
            id=raw.get("id"),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class Transcript:
    events: list[Event] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def of_kind(self, kind: EventKind) -> Iterable[Event]:
        return (e for e in self.events if e.kind == kind)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.to_dict(), sort_keys=True) for e in self.events)

    @classmethod
    def from_events(
        cls, events: Iterable[Event], meta: dict[str, Any] | None = None
    ) -> "Transcript":
        return cls(events=list(events), meta=dict(meta or {}))


def load_transcript_jsonl(path: str | Path) -> Transcript:
    """Load a transcript from a JSONL file (one Event per line)."""
    p = Path(path)
    events: list[Event] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{p}:{lineno}: invalid JSON: {exc}") from exc
        events.append(Event.from_dict(raw))
    return Transcript(events=events, meta={"source": str(p)})


def load_transcript(path: str | Path) -> Transcript:
    """Load a transcript from a JSON or JSONL file.

    JSON form: an object with `events` and optional `meta`, or a bare list
    of events. JSONL form: one event per line.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".jsonl":
        return load_transcript_jsonl(p)
    if suffix == ".json":
        return _load_json_transcript(p)
    text = p.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return load_transcript_jsonl(p)
    return _materialize_json(p, raw)


def _load_json_transcript(p: Path) -> Transcript:
    raw = json.loads(p.read_text(encoding="utf-8"))
    return _materialize_json(p, raw)


def _materialize_json(p: Path, raw: Any) -> Transcript:
    if isinstance(raw, list):
        events = [Event.from_dict(r) for r in raw]
        meta: dict[str, Any] = {"source": str(p)}
    elif isinstance(raw, dict):
        events = [Event.from_dict(r) for r in raw.get("events", [])]
        meta = dict(raw.get("meta", {}))
        meta.setdefault("source", str(p))
    else:
        raise ValueError(f"{p}: top-level JSON must be list or object")
    return Transcript(events=events, meta=meta)
