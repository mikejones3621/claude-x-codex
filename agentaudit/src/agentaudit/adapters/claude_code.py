"""Adapter for Claude Code transcript JSONL.

Claude Code session transcripts emit one JSON object per line with shape:

    {"type": "user", "message": {"content": "..."}}
    {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "..."},
        {"type": "tool_use", "id": "...", "name": "Bash",
         "input": {"command": "ls"}}
    ]}}
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "...", "content": "..."}
    ]}}

This adapter normalizes that into the canonical Event stream.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentaudit.adapters import register
from agentaudit.schema import Event, EventKind, Transcript


def load(path: Path) -> Transcript:
    events: list[Event] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        events.extend(_convert(raw))
    return Transcript(events=events, meta={"source": str(path), "format": "claude_code"})


def _convert(raw: dict) -> list[Event]:
    out: list[Event] = []
    type_ = raw.get("type")
    msg = raw.get("message") or {}
    ts = raw.get("timestamp")
    actor = "user" if type_ == "user" else "assistant" if type_ == "assistant" else (type_ or "")

    content = msg.get("content")
    if isinstance(content, str):
        out.append(Event(kind=EventKind.MESSAGE, actor=actor, content=content, timestamp=ts))
        return out
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                out.append(
                    Event(
                        kind=EventKind.MESSAGE,
                        actor=actor,
                        content=str(block.get("text", "")),
                        timestamp=ts,
                    )
                )
            elif btype == "thinking":
                out.append(
                    Event(
                        kind=EventKind.REASONING,
                        actor=actor,
                        content=str(block.get("thinking", block.get("text", ""))),
                        timestamp=ts,
                    )
                )
            elif btype == "tool_use":
                out.append(
                    Event(
                        kind=EventKind.TOOL_CALL,
                        actor=actor,
                        content="",
                        data={
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                            "id": block.get("id"),
                        },
                        timestamp=ts,
                        id=block.get("id"),
                    )
                )
            elif btype == "tool_result":
                result_content = block.get("content")
                if isinstance(result_content, list):
                    text_parts = [
                        b.get("text", "") for b in result_content if isinstance(b, dict)
                    ]
                    text = "\n".join(text_parts)
                else:
                    text = str(result_content or "")
                out.append(
                    Event(
                        kind=EventKind.TOOL_RESULT,
                        actor="tool",
                        content=text,
                        data={
                            "tool_use_id": block.get("tool_use_id"),
                            "is_error": bool(block.get("is_error", False)),
                        },
                        timestamp=ts,
                        id=block.get("tool_use_id"),
                    )
                )
    return out


register("claude_code", load)
