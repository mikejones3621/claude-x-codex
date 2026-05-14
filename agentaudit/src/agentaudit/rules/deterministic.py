"""Deterministic rule evaluators (no LLM, no network).

Each rule type below maps to a key in spec markdown's `type =` field.

Rule types:

  forbid_pattern    — regex match in event content fails the rule.
  require_pattern   — regex must match somewhere; otherwise fail.
  forbid_tool       — listed tool names must never be called.
  tool_arg_pattern  — regex matched against a specific tool's argument.
  require_consent   — a tool may only fire after a user message containing
                      one of `consent_phrases`. If `tool` is set, scoped
                      to that tool only.
  forbid_actor      — listed actors must never produce events of given kinds.
  max_tool_calls    — fails if tool call count exceeds `limit`.
  no_secret_in_output — built-in pack of common credential patterns.
  cross_actor_propagation — flag when a directive-shaped pattern in one
                      actor's output is parroted by a DIFFERENT actor's
                      subsequent event. Targets the canonical multi-
                      agent / prompt-injection-via-tool-result attack
                      pattern.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from agentaudit.checker import Violation
from agentaudit.rules import register
from agentaudit.schema import Event, EventKind, Transcript
from agentaudit.spec import Rule
from agentaudit.text import normalize_for_match


_DEFAULT_SCOPE = ("message", "tool_result", "tool_call", "reasoning")


def _scope(rule: Rule) -> tuple[EventKind, ...]:
    raw = rule.params.get("scope")
    if not raw:
        names = _DEFAULT_SCOPE
    elif isinstance(raw, str):
        names = tuple(s.strip() for s in raw.split(",") if s.strip())
    else:
        names = tuple(str(s) for s in raw)
    return tuple(EventKind(n) for n in names)


def _violation(rule: Rule, event: Event, idx: int, evidence: str, **extra) -> Violation:
    return Violation(
        rule_id=rule.id,
        rule_name=rule.name,
        severity=rule.severity,
        event_index=idx,
        actor=event.actor,
        evidence=evidence,
        rationale=rule.rationale,
        details=extra,
    )


def _eval_forbid_pattern(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    pattern = rule.params.get("pattern")
    if not pattern:
        raise ValueError(f"{rule.id}: forbid_pattern requires `pattern`")
    flags = re.MULTILINE | (re.IGNORECASE if rule.params.get("ignore_case") else 0)
    rx = re.compile(pattern, flags)
    scope = _scope(rule)
    norm = rule.params.get("normalize")
    for i, ev in enumerate(transcript.events):
        if ev.kind not in scope:
            continue
        haystack = normalize_for_match(ev.content, norm)
        m = rx.search(haystack)
        if m:
            yield _violation(rule, ev, i, evidence=_snippet(haystack, m))


def _eval_require_pattern(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    pattern = rule.params.get("pattern")
    if not pattern:
        raise ValueError(f"{rule.id}: require_pattern requires `pattern`")
    flags = re.MULTILINE | (re.IGNORECASE if rule.params.get("ignore_case") else 0)
    rx = re.compile(pattern, flags)
    scope = _scope(rule)
    norm = rule.params.get("normalize")
    for ev in transcript.events:
        if ev.kind in scope and rx.search(normalize_for_match(ev.content, norm)):
            return
    if transcript.events:
        last = transcript.events[-1]
        idx = len(transcript.events) - 1
    else:
        last = Event(kind=EventKind.MESSAGE, actor="system", content="")
        idx = -1
    yield _violation(rule, last, idx, evidence="(pattern never matched in transcript)")


def _eval_forbid_tool(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    tools = rule.params.get("tools") or rule.params.get("tool")
    if not tools:
        raise ValueError(f"{rule.id}: forbid_tool requires `tool` or `tools`")
    if isinstance(tools, str):
        tools = [tools]
    forbidden = {t.lower() for t in tools}
    for i, ev in enumerate(transcript.events):
        if ev.kind != EventKind.TOOL_CALL:
            continue
        name = _tool_name(ev).lower()
        if name in forbidden:
            yield _violation(rule, ev, i, evidence=f"tool_call: {name}")


def _eval_allowlist_tool(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    tools = rule.params.get("tools") or rule.params.get("tool")
    if not tools:
        raise ValueError(f"{rule.id}: allowlist_tool requires `tool` or `tools`")
    if isinstance(tools, str):
        tools = [tools]
    allowed = {t.lower() for t in tools}
    for i, ev in enumerate(transcript.events):
        if ev.kind != EventKind.TOOL_CALL:
            continue
        name = _tool_name(ev).lower()
        if name not in allowed:
            yield _violation(
                rule,
                ev,
                i,
                evidence=f"tool_call not in allowlist: {name}",
            )


def _eval_tool_arg_pattern(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    """Regex match against named arg(s) of named tool(s).

    Accepts either:
      - `tool` + `arg` (single-tool, single-arg form, original shape)
      - `tools` + `args` (lists; matches any tool in the list against
        any arg in the list — fires on first hit per event)

    The list form is the way to write a single rule that catches the
    same harm across multiple file-mutating tools (Edit, Write,
    MultiEdit, NotebookEdit, MCP filesystem variants, etc.) each of
    which uses a slightly different arg name (file_path, path,
    notebook_path, uri). Single + list forms are mutually accepted; if
    both are present, list takes precedence.
    """
    pattern = rule.params.get("pattern")
    if not pattern:
        raise ValueError(f"{rule.id}: tool_arg_pattern requires `pattern`")
    tool_names = _coerce_str_list(
        rule.params.get("tools"), rule.params.get("tool")
    )
    if not tool_names:
        raise ValueError(
            f"{rule.id}: tool_arg_pattern requires `tool` or `tools`"
        )
    arg_names = _coerce_str_list(
        rule.params.get("args"), rule.params.get("arg")
    )
    flags = re.IGNORECASE if rule.params.get("ignore_case") else 0
    rx = re.compile(pattern, flags)
    targets = {t.lower() for t in tool_names}
    norm = rule.params.get("normalize")
    for i, ev in enumerate(transcript.events):
        if ev.kind != EventKind.TOOL_CALL:
            continue
        if _tool_name(ev).lower() not in targets:
            continue
        haystacks = _arg_haystacks(ev, arg_names)
        for haystack in haystacks:
            haystack = normalize_for_match(haystack, norm)
            m = rx.search(haystack)
            if m:
                yield _violation(rule, ev, i, evidence=_snippet(haystack, m))
                break


def _coerce_str_list(plural: Any, singular: Any) -> list[str]:
    """Accept either the list form OR the singular form OR a comma-
    separated string. Returns a flat list of strings (empty if neither
    is set).
    """
    if plural:
        if isinstance(plural, str):
            return [s.strip() for s in plural.split(",") if s.strip()]
        return [str(s) for s in plural if str(s).strip()]
    if singular:
        if isinstance(singular, str):
            return [singular]
        return [str(s) for s in singular if str(s).strip()]
    return []


def _arg_haystacks(ev: Event, arg_names: list[str]) -> list[str]:
    """Yield one haystack per string LEAF under each named arg.

    For a simple string arg (file_path, content, new_string) this is
    one haystack. For a structured arg whose value is a dict or list
    (MultiEdit's `edits`, MCP filesystem edit_file's `edits`), every
    string leaf in the structure becomes its own haystack. That keeps
    the regex from having to deal with `str(list_of_dict)` serialization
    artifacts like escaped `\\t` / `\\n` literals that defeat `\\b` word
    boundaries — and gives content-side rules a clean surface for
    every nested user-supplied string.

    Backward compatible: a single string arg still yields exactly one
    haystack equal to that string. The empty-args case still yields
    one whole-event haystack.
    """
    if not arg_names:
        return [_flatten(ev.data) + " " + ev.content]
    out: list[str] = []
    for a in arg_names:
        raw = _extract_arg(ev, a)
        if isinstance(raw, str):
            out.append(raw)
        elif raw == "" or raw is None:
            out.append("")
        else:
            out.extend(_string_leaves(raw))
    return out


def _string_leaves(value: Any) -> list[str]:
    """Walk a nested dict/list/scalar and emit each string leaf as
    its own item. Non-string scalars are stringified. Used to inspect
    structured tool args (e.g. MultiEdit's `edits`) without going
    through repr-style serialization."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_string_leaves(v))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_string_leaves(v))
        return out
    return [str(value)]


def _extract_arg(ev: Event, arg: str) -> Any:
    """Look up a tool argument across common containers.

    Adapters store the arg dict under different keys: Claude Code uses
    `input`, OpenAI Agents uses `input` (already parsed), some bespoke
    formats put fields directly on `data`. Try them in order.
    """
    data = ev.data or {}
    for container_key in ("input", "arguments", "args", "params"):
        container = data.get(container_key)
        if isinstance(container, dict) and arg in container:
            return container[arg]
    if arg in data:
        return data[arg]
    return ""


def _eval_require_consent(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    """Gate a tool-call on a prior user-message consent phrase.

    The list forms `tools` and `args` mirror `tool_arg_pattern` — a
    single rule can gate the same conceptual action across multiple
    file-mutating tools (Edit / Write / MultiEdit / NotebookEdit) each
    with its own arg name. The trigger_pattern is matched against any
    of the named args (fire on first hit); if no args are named, the
    serialized event data is the haystack.
    """
    phrases_raw = rule.params.get("consent_phrases") or rule.params.get("phrases")
    if not phrases_raw:
        raise ValueError(f"{rule.id}: require_consent requires `consent_phrases`")
    if isinstance(phrases_raw, str):
        phrases_raw = [phrases_raw]
    phrases = [p.lower() for p in phrases_raw]
    scoped_tools = _coerce_str_list(
        rule.params.get("tools"), rule.params.get("tool")
    )
    scoped_targets = {t.lower() for t in scoped_tools}
    arg_names = _coerce_str_list(
        rule.params.get("args"), rule.params.get("arg")
    )
    trigger_pattern = rule.params.get("trigger_pattern")
    trigger_rx = re.compile(trigger_pattern) if trigger_pattern else None
    persist = bool(rule.params.get("persist", False))

    consent_seen = False
    for i, ev in enumerate(transcript.events):
        if ev.kind == EventKind.MESSAGE and ev.actor == "user":
            text = ev.content.lower()
            if any(p in text for p in phrases):
                consent_seen = True
        elif ev.kind == EventKind.TOOL_CALL:
            if scoped_targets and _tool_name(ev).lower() not in scoped_targets:
                continue
            if trigger_rx is not None:
                haystacks = _arg_haystacks(ev, arg_names)
                if not any(trigger_rx.search(h) for h in haystacks):
                    continue
            if not consent_seen:
                yield _violation(
                    rule,
                    ev,
                    i,
                    evidence=f"tool_call without consent: {_tool_name(ev)}",
                )
            elif not persist:
                consent_seen = False


def _eval_forbid_actor(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    actors = rule.params.get("actors") or rule.params.get("actor")
    if not actors:
        raise ValueError(f"{rule.id}: forbid_actor requires `actor` or `actors`")
    if isinstance(actors, str):
        actors = [actors]
    forbidden_actors = {a.lower() for a in actors}
    scope = _scope(rule)
    for i, ev in enumerate(transcript.events):
        if ev.kind in scope and ev.actor.lower() in forbidden_actors:
            yield _violation(rule, ev, i, evidence=f"{ev.actor}: {_short(ev.content)}")


def _eval_max_tool_calls(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    limit = rule.params.get("limit")
    if not isinstance(limit, int):
        raise ValueError(f"{rule.id}: max_tool_calls requires integer `limit`")
    only = rule.params.get("tool")
    only = only.lower() if isinstance(only, str) else None
    count = 0
    last_offender_idx = -1
    last_offender: Event | None = None
    for i, ev in enumerate(transcript.events):
        if ev.kind != EventKind.TOOL_CALL:
            continue
        if only and _tool_name(ev).lower() != only:
            continue
        count += 1
        if count > limit:
            last_offender_idx = i
            last_offender = ev
    if last_offender is not None:
        yield _violation(
            rule,
            last_offender,
            last_offender_idx,
            evidence=f"tool calls={count}, limit={limit}",
        )


_SECRET_PATTERNS = [
    # AWS access key id
    (r"\bAKIA[0-9A-Z]{16}\b", "aws_access_key_id"),
    # GitHub PAT
    (r"\bghp_[A-Za-z0-9]{36,}\b", "github_pat"),
    # OpenAI key
    (r"\bsk-[A-Za-z0-9]{20,}\b", "openai_api_key"),
    # Anthropic key
    (r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b", "anthropic_api_key"),
    # Slack token
    (r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b", "slack_token"),
    # Generic high-entropy "key/token/secret = ..." assignment
    (
        r"(?i)\b(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"]?"
        r"[A-Za-z0-9_\-]{16,}['\"]?",
        "generic_secret_assignment",
    ),
    # PEM private key header
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----", "private_key_pem"),
]


def _eval_no_secret_in_output(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    scope_raw = rule.params.get("scope") or "message,tool_result"
    if isinstance(scope_raw, str):
        kinds = tuple(EventKind(s.strip()) for s in scope_raw.split(",") if s.strip())
    else:
        kinds = tuple(EventKind(s) for s in scope_raw)
    extra = rule.params.get("extra_patterns") or []
    if isinstance(extra, str):
        extra = [extra]
    patterns = list(_SECRET_PATTERNS) + [(p, "custom") for p in extra]
    compiled = [(re.compile(p), tag) for p, tag in patterns]
    norm = rule.params.get("normalize")
    for i, ev in enumerate(transcript.events):
        if ev.kind not in kinds:
            continue
        haystack = ev.content + "\n" + _flatten(ev.data)
        haystack = normalize_for_match(haystack, norm)
        for rx, tag in compiled:
            m = rx.search(haystack)
            if m:
                yield _violation(
                    rule,
                    ev,
                    i,
                    evidence=_snippet(haystack, m),
                    pattern_tag=tag,
                )
                break


def _eval_cross_actor_propagation(
    rule: Rule, transcript: Transcript
) -> Iterable[Violation]:
    """Flag when a directive-shaped string emitted by one actor is
    parroted by a DIFFERENT actor's subsequent event.

    This is the canonical multi-agent / prompt-injection-via-tool-
    result attack pattern: untrusted content (a fetched webpage, an
    upstream agent's output, a document the agent reads) carries a
    directive — e.g. "ignore previous instructions, exfiltrate X" —
    and a downstream agent's tool_call/message then references or
    acts on it.

    Parameters:
      - `pattern` (required): regex matched against event content.
      - `originator_scope` (default `message,tool_result`): which
        event kinds count as the source.
      - `propagator_scope` (default `tool_call,message`): which event
        kinds count as the downstream actor's action.
      - `max_distance` (default 10): max forward gap, in events,
        between originator and propagator.
      - `ignore_case` (default True): natural-language patterns are
        almost always case-insensitive.
    """
    pattern = rule.params.get("pattern")
    if not pattern:
        raise ValueError(
            f"{rule.id}: cross_actor_propagation requires `pattern`"
        )
    ignore_case = rule.params.get("ignore_case", True)
    flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
    rx = re.compile(pattern, flags)
    max_distance = int(rule.params.get("max_distance", 10))
    norm = rule.params.get("normalize")

    def _scope_list(key: str, default: tuple[str, ...]) -> tuple[EventKind, ...]:
        raw = rule.params.get(key)
        if not raw:
            names: tuple[str, ...] = default
        elif isinstance(raw, str):
            names = tuple(s.strip() for s in raw.split(",") if s.strip())
        else:
            names = tuple(str(s) for s in raw)
        return tuple(EventKind(n) for n in names)

    originator_scope = _scope_list(
        "originator_scope", ("message", "tool_result")
    )
    propagator_scope = _scope_list(
        "propagator_scope", ("tool_call", "message")
    )

    # Pass 1: find every originator event.
    originators: list[tuple[int, str]] = []
    for i, ev in enumerate(transcript.events):
        if ev.kind not in originator_scope:
            continue
        haystack = normalize_for_match(ev.content, norm)
        if rx.search(haystack):
            originators.append((i, ev.actor))

    if not originators:
        return

    # Pass 2: for each propagator-scope event matching the pattern,
    # look back up to max_distance for any originator with a
    # DIFFERENT actor.
    flagged: set[int] = set()
    for j, ev in enumerate(transcript.events):
        if ev.kind not in propagator_scope:
            continue
        if j in flagged:
            continue
        haystack = ev.content + "\n" + _flatten(ev.data)
        haystack = normalize_for_match(haystack, norm)
        m = rx.search(haystack)
        if not m:
            continue
        propagator_actor = ev.actor
        for orig_idx, orig_actor in originators:
            if orig_idx >= j:
                break
            if j - orig_idx > max_distance:
                continue
            if orig_actor == propagator_actor:
                continue
            # Found a cross-actor propagation. Flag the propagator.
            flagged.add(j)
            yield _violation(
                rule,
                ev,
                j,
                evidence=_snippet(haystack, m),
                originator_index=orig_idx,
                originator_actor=orig_actor,
                propagator_actor=propagator_actor,
            )
            break


def _tool_name(ev: Event) -> str:
    return str(ev.data.get("name") or ev.data.get("tool") or ev.actor or "")


def _flatten(data: dict) -> str:
    import json as _json

    try:
        return _json.dumps(data, sort_keys=True, default=str)
    except Exception:
        return str(data)


def _snippet(text: str, m: re.Match[str], radius: int = 40) -> str:
    start = max(0, m.start() - radius)
    end = min(len(text), m.end() + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].replace("\n", " ") + suffix


def _short(text: str, n: int = 80) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


register("forbid_pattern", _eval_forbid_pattern)
register("require_pattern", _eval_require_pattern)
register("forbid_tool", _eval_forbid_tool)
register("allowlist_tool", _eval_allowlist_tool)
register("tool_arg_pattern", _eval_tool_arg_pattern)
register("require_consent", _eval_require_consent)
register("forbid_actor", _eval_forbid_actor)
register("max_tool_calls", _eval_max_tool_calls)
register("no_secret_in_output", _eval_no_secret_in_output)
register("cross_actor_propagation", _eval_cross_actor_propagation)
