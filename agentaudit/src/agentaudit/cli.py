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
        help="path to a spec markdown file (repeatable)",
    )
    chk.add_argument(
        "--bundled-specs",
        choices=("all", "cli-safe", "deterministic", "deployment-specific"),
        help=(
            "include bundled specs by group: `cli-safe` runs only cross-deployment "
            "deterministic specs, `deployment-specific` runs only deployment-specific "
            "deterministic specs, `deterministic` includes both deterministic groups, "
            "and `all` also includes judge-backed specs"
        ),
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

    ls = sub.add_parser("list-specs", help="list bundled spec markdown files")
    ls.add_argument(
        "--verbose",
        action="store_true",
        help="include bundled spec classification details",
    )
    ls.add_argument(
        "--cli-safe",
        action="store_true",
        help="show only bundled specs that are cross-deployment safe to run directly in the CLI",
    )
    ls.add_argument(
        "--deployment-specific",
        action="store_true",
        help="show only bundled specs that encode deployment-specific deterministic policy",
    )
    ls.set_defaults(_handler=_cmd_list_specs)

    w = sub.add_parser(
        "watch",
        help=(
            "live-blocking mode: evaluate one or many incoming events against "
            "loaded specs and emit allow/block decisions for an agent runtime hook"
        ),
    )
    w.add_argument(
        "--spec",
        action="append",
        help="path to a spec markdown file (repeatable)",
    )
    w.add_argument(
        "--bundled-specs",
        choices=("all", "cli-safe", "deterministic", "deployment-specific"),
        help="include bundled specs by group (same semantics as `agentaudit check`)",
    )
    w.add_argument(
        "--mode",
        choices=("hook", "stream"),
        default="hook",
        help=(
            "hook: read one JSON event from stdin, decide, exit (default — "
            "designed for per-tool-call hooks). stream: read line-delimited "
            "events from stdin forever, emit line-delimited decisions on stdout."
        ),
    )
    w.add_argument(
        "--history-file",
        type=Path,
        help=(
            "JSONL path that persists transcript history between hook-mode "
            "invocations. Required for rules that need cross-event context "
            "(notably `require_consent`). Allowed events are appended on "
            "successful evaluations."
        ),
    )
    w.add_argument(
        "--block-severity",
        choices=("low", "medium", "high", "critical"),
        default="high",
        help=(
            "minimum severity that triggers a block decision. Violations "
            "below this severity are still reported but allowed through."
        ),
    )
    w.add_argument(
        "--log-file",
        type=Path,
        help="append decisions (including allows with sub-threshold findings) to this JSONL file",
    )
    w.add_argument(
        "--persist-blocked-events",
        action="store_true",
        help=(
            "also append blocked events to the history file. Default is to "
            "drop blocked events on the floor, since by definition the "
            "runtime did not execute them."
        ),
    )
    w.set_defaults(_handler=_cmd_watch)

    rp = sub.add_parser(
        "replay",
        help=(
            "replay a stored transcript through the live-blocking pipeline "
            "and report what would have been blocked"
        ),
    )
    rp.add_argument("transcript", help="path to a transcript file (.json or .jsonl)")
    rp.add_argument(
        "--spec",
        action="append",
        help="path to a spec markdown file (repeatable)",
    )
    rp.add_argument(
        "--bundled-specs",
        choices=("all", "cli-safe", "deterministic", "deployment-specific"),
        help="include bundled specs by group (same semantics as `agentaudit check`)",
    )
    rp.add_argument(
        "--adapter",
        choices=list_adapters(),
        help="adapter name to use when reading the transcript (default: auto-detect)",
    )
    rp.add_argument(
        "--block-severity",
        choices=("low", "medium", "high", "critical"),
        default="high",
        help="minimum severity that triggers a block decision",
    )
    rp.add_argument(
        "--log-file",
        type=Path,
        help="append decisions to this JSONL file",
    )
    rp.set_defaults(_handler=_cmd_replay)

    ig = sub.add_parser(
        "ingest",
        help=(
            "record a single event into a watcher history file without "
            "evaluating it (companion to `watch` for user-message hooks)"
        ),
    )
    ig.add_argument(
        "--history-file",
        type=Path,
        required=True,
        help="JSONL history file to append the event to",
    )
    ig.add_argument(
        "--actor",
        default="user",
        help="actor name for the wrapped event when input is not a full Event JSON (default: user)",
    )
    ig.add_argument(
        "--event-kind",
        default="message",
        choices=("message", "tool_call", "tool_result", "reasoning"),
        help="event kind for the wrapped event (default: message)",
    )
    ig.set_defaults(_handler=_cmd_ingest)

    return p


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        if args.adapter:
            transcript = load_with_adapter(args.adapter, args.transcript)
        else:
            transcript = _auto_load(Path(args.transcript))
        all_violations = []
        spec_paths = _resolve_requested_specs(args)
        if not spec_paths:
            sys.stderr.write(
                "error: pass at least one `--spec` or choose `--bundled-specs`.\n"
            )
            return 2
        for spec_path in spec_paths:
            spec = load_spec(_resolve_spec_path(spec_path))
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


def _cmd_watch(args: argparse.Namespace) -> int:
    from agentaudit.watch import run_hook_mode, run_stream_mode

    try:
        spec_paths = _resolve_requested_specs(args)
        if not spec_paths:
            sys.stderr.write(
                "error: pass at least one `--spec` or choose `--bundled-specs`.\n"
            )
            return 2
        specs = [load_spec(_resolve_spec_path(p)) for p in spec_paths]
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if args.mode == "hook":
        return run_hook_mode(
            sys.stdin,
            sys.stdout,
            specs,
            history_file=args.history_file,
            log_file=args.log_file,
            block_severity=args.block_severity,
            persist_blocked_events=args.persist_blocked_events,
        )
    return run_stream_mode(
        sys.stdin,
        sys.stdout,
        specs,
        log_file=args.log_file,
        block_severity=args.block_severity,
        persist_blocked_events=args.persist_blocked_events,
    )


def _cmd_ingest(args: argparse.Namespace) -> int:
    from agentaudit.watch import run_ingest

    rc = run_ingest(
        sys.stdin,
        args.history_file,
        actor=args.actor,
        event_kind=args.event_kind,
    )
    if rc == 2:
        sys.stderr.write("error: ingest received empty stdin; refusing to record nothing\n")
    return rc


def _cmd_replay(args: argparse.Namespace) -> int:
    from agentaudit.watch import run_replay

    try:
        if args.adapter:
            transcript = load_with_adapter(args.adapter, args.transcript)
        else:
            transcript = _auto_load(Path(args.transcript))
        spec_paths = _resolve_requested_specs(args)
        if not spec_paths:
            sys.stderr.write(
                "error: pass at least one `--spec` or choose `--bundled-specs`.\n"
            )
            return 2
        specs = [load_spec(_resolve_spec_path(p)) for p in spec_paths]
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    return run_replay(
        transcript,
        sys.stdout,
        specs,
        log_file=args.log_file,
        block_severity=args.block_severity,
    )


def _cmd_list_rules(args: argparse.Namespace) -> int:
    from agentaudit.rules import known_types

    for t in known_types():
        print(t)
    return 0


def _cmd_list_adapters(args: argparse.Namespace) -> int:
    for adapter in list_adapters():
        print(adapter)
    return 0


def _cmd_list_specs(args: argparse.Namespace) -> int:
    spec_paths = _list_bundled_specs()
    if not spec_paths:
        sys.stderr.write("error: bundled specs are not available in this install.\n")
        return 2
    for spec_path in spec_paths:
        classification = _classify_spec(_resolve_spec_path(spec_path))
        if args.cli_safe and classification != "deterministic":
            continue
        if args.deployment_specific and classification != "deterministic+deployment-specific":
            continue
        if args.verbose:
            print(f"{spec_path}\t{classification}")
        else:
            print(spec_path)
    return 0


def _resolve_spec_path(spec_path: str | Path) -> str | Path:
    p = Path(spec_path)
    if p.exists():
        return p

    specs_dir = _find_bundled_specs_dir()
    if specs_dir is None:
        return spec_path

    candidate = specs_dir / p
    if candidate.exists():
        return candidate
    return spec_path


def _resolve_requested_specs(args: argparse.Namespace) -> list[str]:
    spec_paths = list(args.spec or [])
    if not args.bundled_specs:
        return _dedupe_spec_paths(spec_paths)
    if args.bundled_specs == "all":
        spec_paths.extend(_list_bundled_specs())
        return _dedupe_spec_paths(spec_paths)
    if args.bundled_specs == "deployment-specific":
        spec_paths.extend(_list_deployment_specific_specs())
        return _dedupe_spec_paths(spec_paths)
    if args.bundled_specs == "deterministic":
        spec_paths.extend(_list_deterministic_specs())
        return _dedupe_spec_paths(spec_paths)
    if args.bundled_specs == "cli-safe":
        spec_paths.extend(_list_cli_safe_specs())
        return _dedupe_spec_paths(spec_paths)
    return _dedupe_spec_paths(spec_paths)


def _list_bundled_specs() -> list[str]:
    specs_dir = _find_bundled_specs_dir()
    if specs_dir is None:
        return []
    return sorted(
        path.relative_to(specs_dir).as_posix() for path in specs_dir.rglob("*.md")
    )


def _list_cli_safe_specs() -> list[str]:
    return [
        spec_path
        for spec_path in _list_bundled_specs()
        if _classify_spec(_resolve_spec_path(spec_path)) == "deterministic"
    ]


def _list_deterministic_specs() -> list[str]:
    return [
        spec_path
        for spec_path in _list_bundled_specs()
        if _classify_spec(_resolve_spec_path(spec_path))
        in {"deterministic", "deterministic+deployment-specific"}
    ]


def _list_deployment_specific_specs() -> list[str]:
    return [
        spec_path
        for spec_path in _list_bundled_specs()
        if _classify_spec(_resolve_spec_path(spec_path))
        == "deterministic+deployment-specific"
    ]


def _dedupe_spec_paths(spec_paths: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for spec_path in spec_paths:
        resolved = _resolve_spec_path(spec_path)
        key = str(Path(resolved))
        if key in seen:
            continue
        seen.add(key)
        out.append(spec_path)
    return out


def _classify_spec(spec_path: str | Path) -> str:
    spec = load_spec(spec_path)
    if any(rule.type == "judge" for rule in spec.rules):
        return "judge-backed"
    if any(rule.type == "allowlist_tool" for rule in spec.rules):
        return "deterministic+deployment-specific"
    return "deterministic"


def _find_bundled_specs_dir() -> Path | None:
    here = Path(__file__).resolve()
    candidates = (here.parent / "specs", here.parents[2] / "specs")
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_dir():
            return resolved
    return None


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
    if args.cmd == "list-specs":
        return _cmd_list_specs(args)
    if args.cmd == "watch":
        return _cmd_watch(args)
    if args.cmd == "replay":
        return _cmd_replay(args)
    if args.cmd == "ingest":
        return _cmd_ingest(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
