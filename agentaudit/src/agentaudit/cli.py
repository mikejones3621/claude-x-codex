"""agentaudit command-line interface."""

from __future__ import annotations

import argparse
import difflib
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


# Intent-based aliases for the bundled-spec groups, so a newcomer does
# not have to learn the internal taxonomy to get started. `recommended`
# is the safe starting point; `strict` turns everything on.
_GROUP_ALIASES = {"recommended": "cli-safe", "strict": "all"}
_BUNDLED_CHOICES = (
    "recommended",
    "strict",
    "all",
    "cli-safe",
    "deterministic",
    "deployment-specific",
)


class _UserError(Exception):
    """A user-facing error, reported as `error: <msg>` with exit code 2.

    Used to turn expected failures (missing files, typo'd spec names,
    unparseable transcripts) into clean messages instead of tracebacks.
    """


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
        choices=_BUNDLED_CHOICES,
        help=(
            "include bundled specs by group. Start with `recommended` "
            "(alias for `cli-safe`): cross-deployment deterministic specs "
            "that are safe to run anywhere. `strict` (alias for `all`) "
            "also includes judge-backed specs. With no `--spec` and no "
            "`--bundled-specs`, `check` runs the `recommended` set."
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
        "--describe",
        action="store_true",
        help="show a human-readable summary of the rules in each spec",
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
        choices=_BUNDLED_CHOICES,
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
        choices=_BUNDLED_CHOICES,
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

    ih = sub.add_parser(
        "install-hook",
        help="scaffold agent-runtime hook scripts into a project",
    )
    ih.add_argument(
        "runtime",
        choices=("claude-code",),
        help="which agent runtime to scaffold hooks for",
    )
    ih.add_argument(
        "--dir",
        type=Path,
        default=Path("."),
        help="project directory to install into (default: current directory)",
    )
    ih.add_argument(
        "--force",
        action="store_true",
        help="overwrite hook scripts that already exist",
    )
    ih.add_argument(
        "--write-settings",
        action="store_true",
        help=(
            "merge the hooks block into .claude/settings.json. Without this "
            "flag the snippet is printed for you to paste."
        ),
    )
    ih.set_defaults(_handler=_cmd_install_hook)

    return p


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        transcript = _load_transcript(args)
        applied_default = not (args.spec or args.bundled_specs)
        spec_paths = _resolve_requested_specs(args, default_group="cli-safe")
        if not spec_paths:
            raise _UserError("pass at least one `--spec` or choose `--bundled-specs`.")
        if applied_default:
            sys.stderr.write(
                "note: no specs given; running the recommended `cli-safe` set "
                "(pass --spec or --bundled-specs to choose).\n"
            )
        specs = _load_specs(spec_paths)
    except _UserError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    all_violations = []
    try:
        for spec in specs:
            all_violations.extend(check(transcript, spec))
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
    all_violations.sort(key=lambda v: (-v.severity_rank, v.event_index, v.rule_id))

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
            raise _UserError("pass at least one `--spec` or choose `--bundled-specs`.")
        specs = _load_specs(spec_paths)
    except _UserError as exc:
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
        transcript = _load_transcript(args)
        applied_default = not (args.spec or args.bundled_specs)
        spec_paths = _resolve_requested_specs(args, default_group="cli-safe")
        if not spec_paths:
            raise _UserError("pass at least one `--spec` or choose `--bundled-specs`.")
        if applied_default:
            sys.stderr.write(
                "note: no specs given; replaying against the recommended `cli-safe` set "
                "(pass --spec or --bundled-specs to choose).\n"
            )
        specs = _load_specs(spec_paths)
    except _UserError as exc:
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
        if args.describe:
            print(spec_path)
            print(f"    {_describe_spec(_resolve_spec_path(spec_path))}")
        elif args.verbose:
            print(f"{spec_path}\t{classification}")
        else:
            print(spec_path)
    return 0


def _cmd_install_hook(args: argparse.Namespace) -> int:
    from agentaudit.hooks import install_claude_code_hooks

    if args.runtime != "claude-code":
        sys.stderr.write(f"error: unsupported runtime: {args.runtime}\n")
        return 2
    try:
        result = install_claude_code_hooks(
            args.dir, force=args.force, write_settings=args.write_settings
        )
    except OSError as exc:
        sys.stderr.write(f"error: {exc.strerror or exc}\n")
        return 2

    for path in result.written:
        print(f"wrote {path}")
    for path in result.skipped:
        print(f"skipped {path} (already exists; pass --force to overwrite)")

    if result.settings_written:
        print(f"merged hooks into {result.settings_path}")
    else:
        print()
        print(f"Add this to {result.settings_path} (or re-run with --write-settings):")
        print(result.settings_snippet)
    return 0


def _describe_spec(spec_path: str | Path) -> str:
    spec = load_spec(spec_path)
    if not spec.rules:
        return "(no rules)"
    return "; ".join(rule.name for rule in spec.rules)


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

    # The bundled directory is itself named `specs/`, so a `specs/`-prefixed
    # reference (e.g. `specs/no-secret-leak.md`) is a natural thing to type
    # and is how the in-repo recipes refer to specs. Resolve it against the
    # bundled dir by dropping the leading `specs/` component.
    if p.parts and p.parts[0] == "specs":
        nested = specs_dir / Path(*p.parts[1:])
        if nested.exists():
            return nested

    return spec_path


def _load_transcript(args: argparse.Namespace):
    """Load the transcript named on the command line, mapping IO/parse
    failures to clean `_UserError`s instead of raw tracebacks."""
    path = args.transcript
    try:
        if getattr(args, "adapter", None):
            return load_with_adapter(args.adapter, path)
        return _auto_load(Path(path))
    except FileNotFoundError:
        raise _UserError(f"transcript not found: {path}")
    except IsADirectoryError:
        raise _UserError(f"transcript path is a directory, not a file: {path}")
    except OSError as exc:
        raise _UserError(f"cannot read transcript {path!r}: {exc.strerror or exc}")
    except ValueError as exc:
        raise _UserError(f"could not parse transcript {path!r}: {exc}")


def _load_specs(spec_paths: list[str]):
    """Load each requested spec, mapping IO/parse failures to clean
    `_UserError`s (with a did-you-mean hint for missing spec names)."""
    specs = []
    for spec_path in spec_paths:
        resolved = _resolve_spec_path(spec_path)
        try:
            specs.append(load_spec(resolved))
        except FileNotFoundError:
            raise _UserError(_spec_not_found_message(spec_path))
        except IsADirectoryError:
            raise _UserError(f"spec path is a directory, not a file: {spec_path}")
        except OSError as exc:
            raise _UserError(f"cannot read spec {spec_path!r}: {exc.strerror or exc}")
        except ValueError as exc:
            raise _UserError(f"invalid spec {spec_path!r}: {exc}")
    return specs


def _spec_not_found_message(spec_path: str) -> str:
    lines = [f"spec not found: {spec_path}"]
    suggestion = _closest_bundled_spec(str(spec_path))
    if suggestion:
        lines.append(f"  did you mean: {suggestion}?")
    lines.append("  run `agentaudit list-specs` to see the bundled specs.")
    return "\n".join(lines)


def _closest_bundled_spec(name: str) -> str | None:
    candidates = _list_bundled_specs()
    if not candidates:
        return None
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    base = Path(name).name
    by_base = {Path(c).name: c for c in candidates}
    base_matches = difflib.get_close_matches(base, list(by_base), n=1, cutoff=0.6)
    if base_matches:
        return by_base[base_matches[0]]
    return None


def _resolve_requested_specs(
    args: argparse.Namespace, default_group: str | None = None
) -> list[str]:
    spec_paths = list(args.spec or [])
    group = args.bundled_specs
    if group is None and not spec_paths and default_group is not None:
        group = default_group
    if group is None:
        return _dedupe_spec_paths(spec_paths)
    group = _GROUP_ALIASES.get(group, group)
    if group == "all":
        spec_paths.extend(_list_bundled_specs())
    elif group == "deployment-specific":
        spec_paths.extend(_list_deployment_specific_specs())
    elif group == "deterministic":
        spec_paths.extend(_list_deterministic_specs())
    elif group == "cli-safe":
        spec_paths.extend(_list_cli_safe_specs())
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
    if args.cmd == "install-hook":
        return _cmd_install_hook(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
