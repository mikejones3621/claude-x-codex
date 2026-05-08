"""Adapter for the Anthropic Messages API conversation history format.

This is the canonical request/response shape that any non-Claude-Code
caller of the Anthropic Messages API works with. The agent loop
typically captures the running `messages` array; this adapter
normalises that to the Event stream the rest of agentaudit consumes.

Accepted inputs (auto-detected):

  1. A request-shape envelope with `messages`:
        {"messages": [{"role": "user", "content": ...}, ...]}
  2. A bare list of messages:
        [{"role": "user", "content": ...}, {"role": "assistant", "content": ...}]
  3. A response-shape envelope (single assistant turn):
        {"role": "assistant", "content": [...]}
  4. JSONL with one message per line.

Each message's `content` may be a plain string OR a list of blocks of
type `text`, `thinking`, `tool_use`, or `tool_result`. A user message
that contains a `tool_result` block is mapped to a `tool_result` event
with `actor = "tool"` (matching the convention the claude_code adapter
already uses), so existing rules referring to `actor="tool"` keep
working.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentaudit.adapters import register
from agentaudit.schema import Event, EventKind, Transcript


def load(path: Path) -> Transcript:
    text = path.read_text(encoding="utf-8")
    messages = _load_messages(text)
    events: list[Event] = []
    for msg in messages:
        events.extend(_convert_message(msg))
    return Transcript(
        events=events,
        meta={"source": str(path), "format": "anthropic_messages"},
    )


def _load_messages(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        # JSONL fallback: one message per line.
        return [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]
    return _coerce_messages(raw)


def _coerce_messages(raw: object) -> list[dict]:
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    if not isinstance(raw, dict):
        return []
    msgs = raw.get("messages")
    if isinstance(msgs, list):
        return [m for m in msgs if isinstance(m, dict)]
    # Response-shape envelope: a single assistant turn at the top level.
    if "role" in raw and "content" in raw:
        return [raw]
    return []


def _convert_message(msg: dict) -> list[Event]:
    role = msg.get("role", "")
    actor = role if role in ("user", "assistant", "system") else "assistant"
    ts = msg.get("timestamp")
    content = msg.get("content")
    out: list[Event] = []

    if isinstance(content, str):
        out.append(
            Event(
                kind=EventKind.MESSAGE,
                actor=actor,
                content=content,
                timestamp=ts,
            )
        )
        return out

    if not isinstance(content, list):
        return out

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
                    actor="assistant",
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
            text = _flatten_tool_result_content(result_content)
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
        # Other block types (image, document, server_tool_use, etc.) are
        # currently dropped silently — they aren't load-bearing for the
        # rule families we ship today. Easy to add when a concrete spec
        # needs them.
    return out


def _flatten_tool_result_content(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif "text" in block:
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(json.dumps(block, sort_keys=True))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        if "text" in value:
            return str(value.get("text", ""))
        return json.dumps(value, sort_keys=True)
    return str(value)


register("anthropic_messages", load)
