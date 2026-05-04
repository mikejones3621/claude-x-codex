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
from pathlib import Path

from agentaudit.adapters import register
from agentaudit.schema import Event, EventKind, Transcript


def load(path: Path) -> Transcript:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    items: list[dict]
    if stripped.startswith("["):
        items = json.loads(text)
    elif stripped.startswith("{") and "\n" not in text.strip():
        items = [json.loads(text)]
    else:
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    events: list[Event] = []
    for raw in items:
        events.extend(_convert(raw))
    return Transcript(
        events=events, meta={"source": str(path), "format": "openai_agents"}
    )


def _convert(raw: dict) -> list[Event]:
    type_ = raw.get("type")
    if type_ == "message":
        return [_message(raw)]
    if type_ == "function_call":
        args = raw.get("arguments")
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
            except json.JSONDecodeError:
                parsed = {"_raw": args}
        else:
            parsed = args or {}
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
                id=raw.get("call_id") or raw.get("id"),
            )
        ]
    if type_ == "function_call_output":
        out = raw.get("output")
        if isinstance(out, (dict, list)):
            text = json.dumps(out, sort_keys=True)
        else:
            text = str(out or "")
        return [
            Event(
                kind=EventKind.TOOL_RESULT,
                actor="tool",
                content=text,
                data={"call_id": raw.get("call_id")},
                id=raw.get("call_id"),
            )
        ]
    if type_ == "reasoning":
        text_parts: list[str] = []
        for block in raw.get("summary") or []:
            if isinstance(block, dict):
                text_parts.append(str(block.get("text", "")))
        return [
            Event(
                kind=EventKind.REASONING,
                actor="assistant",
                content="\n".join(text_parts),
            )
        ]
    return []


def _message(raw: dict) -> Event:
    role = raw.get("role", "assistant")
    content = raw.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        text = "\n".join(parts)
    else:
        text = str(content or "")
    return Event(kind=EventKind.MESSAGE, actor=role, content=text)


register("openai_agents", load)
