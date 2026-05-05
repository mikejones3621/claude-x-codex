"""Adapter for OpenAI Responses / Agents SDK transcripts.

Accepts a JSON file containing a list of items, or a JSONL file with one
item per line. Each item is one of:

    {"type": "message", "role": "user|assistant|system",
     "content": "text" | [{"type": "output_text|input_text", "text": "..."}]}
    {"type": "function_call", "name": "...", "arguments": "..." | {...},
     "call_id": "..."}
    {"type": "function_call_output", "call_id": "...", "output": "..." | {...}}
    {"type": "reasoning", "summary": [{"type": "summary_text", "text": "..."}]}
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from agentaudit.adapters import register
from agentaudit.schema import Event, EventKind, Transcript


def load(path: Path) -> Transcript:
    text = path.read_text(encoding="utf-8")
    items = _load_items(text)
    events: list[Event] = []
    for raw in items:
        events.extend(_convert(raw))
    return Transcript(
        events=events, meta={"source": str(path), "format": "openai_agents"}
    )


def _load_items(text: str) -> list[dict]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return _coerce_items(raw)


def _coerce_items(raw: object) -> list[dict]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []
    for key in ("output", "items"):
        items = raw.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    nested = raw.get("response")
    if isinstance(nested, dict):
        return _coerce_items(nested)
    return [raw]


def _convert(raw: dict) -> list[Event]:
    raw = _unwrap_item(raw)
    type_ = raw.get("type")
    if type_ == "message":
        return [_message(raw)]
    if type_ == "function_call":
        parsed = _parse_arguments(raw.get("arguments", raw.get("input")))
        return [
            Event(
                kind=EventKind.TOOL_CALL,
                actor="assistant",
                content="",
                data={
                    "name": raw.get("name", ""),
                    "input": parsed,
                    "id": raw.get("call_id") or raw.get("id"),
                },
                timestamp=raw.get("timestamp"),
                id=raw.get("call_id") or raw.get("id"),
            )
        ]
    if type_ == "function_call_output":
        out = raw.get("output", raw.get("content"))
        text = _block_text(out)
        return [
            Event(
                kind=EventKind.TOOL_RESULT,
                actor="tool",
                content=text,
                data={"call_id": raw.get("call_id")},
                timestamp=raw.get("timestamp"),
                id=raw.get("call_id"),
            )
        ]
    if type_ == "reasoning":
        return [
            Event(
                kind=EventKind.REASONING,
                actor="assistant",
                content=_block_text(raw.get("summary")),
                timestamp=raw.get("timestamp"),
                id=raw.get("id"),
            )
        ]
    return []


def _message(raw: dict) -> Event:
    role = raw.get("role", "assistant")
    return Event(
        kind=EventKind.MESSAGE,
        actor=role,
        content=_block_text(raw.get("content")),
        timestamp=raw.get("timestamp"),
        id=raw.get("id"),
    )


def _unwrap_item(raw: dict) -> dict:
    for key in ("raw_item", "item"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            return _unwrap_item(nested)
    return raw


def _parse_arguments(value: object) -> dict:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"_raw": value}
        return parsed if isinstance(parsed, dict) else {"_raw": value}
    if isinstance(value, dict):
        return value
    return {}


def _block_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "text" in value:
            return str(value.get("text", ""))
        if "refusal" in value:
            return str(value.get("refusal", ""))
        if "content" in value:
            return _block_text(value.get("content"))
        return json.dumps(value, sort_keys=True)
    if isinstance(value, Iterable):
        parts = [_block_text(part) for part in value]
        return "\n".join(part for part in parts if part)
    if value is None:
        return ""
    return str(value)


register("openai_agents", load)
