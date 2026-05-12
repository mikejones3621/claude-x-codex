"""agentaudit command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentaudit import (
    __version__,
    check,
    load_spec,
    load_transcript,
    render_json,
    render_text,
)
from agentaudit.adapters import load_with_adapter, list_adapters


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentaudit",
        description="Audit LLM agent transcripts against behavior specs.",
    )
    p.add_argument("--version", action="version", version=f"agentaudit {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    chk = sub.add_parser("check", help="check a transcript against one or more specs")
    chk.add_argument("transcript", help="path to a transcript file (.json or .jsonl)")
    chk.add_argument(
        "--spec",
        action="append",
        required=True,
        help="path to a spec markdown file (repeatable)",
    )
    chk.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    chk.add_argument(
        "--adapter",
        choices=list_adapters(),
        help=(
            "adapter name to use when reading the transcript "
            "(default: auto-detect; falls back to native schema)"
        ),
    )
    chk.add_argument(
        "--fail-on",
        choices=("low", "medium", "high", "critical", "any"),
        default="any",
        help="exit code 1 only if violations meet/exceed this severity",
    )
    chk.add_argument(
        "--no-color", action="store_true", help="disable ANSI color in text output"
    )

    ls = sub.add_parser("list-rules", help="list registered rule types")
    ls.set_defaults(_handler=_cmd_list_rules)

    la = sub.add_parser("list-adapters", help="list registered transcript adapters")
    la.set_defaults(_handler=_cmd_list_adapters)

    return p


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        if args.adapter:
            transcript = load_with_adapter(args.adapter, args.transcript)
        else:
            transcript = _auto_load(Path(args.transcript))
        all_violations = []
        for spec_path in args.spec:
            spec = load_spec(spec_path)
            all_violations.extend(check(transcript, spec))
        all_violations.sort(key=lambda v: (-v.severity_rank, v.event_index, v.rule_id))
    except ValueError as exc:
        msg = str(exc)
        if "judge callable is required" in msg:
            sys.stderr.write(
                "error: judge-backed rules are only supported via the Python API; "
                "load the spec with `load_spec(...)` and call `check(..., judge=...)`.\n"
            )
            return 2
        sys.stderr.write(f"error: {msg}\n")
        return 2

    if args.format == "json":
        sys.stdout.write(render_json(all_violations))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(
            render_text(all_violations, color=sys.stdout.isatty() and not args.no_color)
        )

    threshold = {"low": 1, "medium": 2, "high": 3, "critical": 4, "any": 1}[args.fail_on]
    if any(v.severity_rank >= threshold for v in all_violations):
        return 1
    return 0


def _cmd_list_rules(args: argparse.Namespace) -> int:
    from agentaudit.rules import known_types

    for t in known_types():
        print(t)
    return 0


def _cmd_list_adapters(args: argparse.Namespace) -> int:
    for adapter in list_adapters():
        print(adapter)
    return 0


def _auto_load(path: Path):
    """Prefer content sniffing, then filename hints, then native schema."""
    detected = _detect_adapter(path)
    if detected:
        return load_with_adapter(detected, path)

    name = path.name.lower()
    if "claude_code" in name or "claude-code" in name:
        return load_with_adapter("claude_code", path)
    if "anthropic" in name:
        return load_with_adapter("anthropic_messages", path)
    if "openai" in name or "agents_sdk" in name or "agents-sdk" in name:
        return load_with_adapter("openai_agents", path)
    return load_transcript(path)


def _detect_adapter(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return _detect_jsonl_adapter(text)
    return _detect_json_adapter(raw)


def _detect_jsonl_adapter(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return None
        return _detect_json_adapter(raw)
    return None


def _detect_json_adapter(raw: object) -> str | None:
    if isinstance(raw, dict):
        if isinstance(raw.get("messages"), list):
            return "anthropic_messages"
        if isinstance(raw.get("output"), list) or isinstance(raw.get("items"), list):
            return "openai_agents"
        if "role" in raw and "content" in raw:
            return "anthropic_messages"
        if "type" in raw and raw.get("type") in {
            "message",
            "function_call",
            "function_call_output",
            "reasoning",
            "message_output_item",
            "tool_call_item",
            "tool_call_output_item",
            "reasoning_item",
        }:
            return "openai_agents"
        return None
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            if "kind" in item:
                return None
            if "role" in item and "content" in item:
                return "anthropic_messages"
            if item.get("type") in {
                "message",
                "function_call",
                "function_call_output",
                "reasoning",
                "message_output_item",
                "tool_call_item",
                "tool_call_output_item",
                "reasoning_item",
            }:
                return "openai_agents"
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check":
        return _cmd_check(args)
    if args.cmd == "list-rules":
        return _cmd_list_rules(args)
    if args.cmd == "list-adapters":
        return _cmd_list_adapters(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
