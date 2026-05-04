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
"""

from __future__ import annotations

import re
from typing import Iterable

from agentaudit.checker import Violation
from agentaudit.rules import register
from agentaudit.schema import Event, EventKind, Transcript
from agentaudit.spec import Rule


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
    for i, ev in enumerate(transcript.events):
        if ev.kind not in scope:
            continue
        m = rx.search(ev.content)
        if m:
            yield _violation(rule, ev, i, evidence=_snippet(ev.content, m))


def _eval_require_pattern(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    pattern = rule.params.get("pattern")
    if not pattern:
        raise ValueError(f"{rule.id}: require_pattern requires `pattern`")
    flags = re.MULTILINE | (re.IGNORECASE if rule.params.get("ignore_case") else 0)
    rx = re.compile(pattern, flags)
    scope = _scope(rule)
    for ev in transcript.events:
        if ev.kind in scope and rx.search(ev.content):
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


def _eval_tool_arg_pattern(rule: Rule, transcript: Transcript) -> Iterable[Violation]:
    tool = rule.params.get("tool")
    pattern = rule.params.get("pattern")
    if not tool or not pattern:
        raise ValueError(f"{rule.id}: tool_arg_pattern requires `tool` and `pattern`")
    arg = rule.params.get("arg")  # optional; if omitted, search whole serialized data
    flags = re.IGNORECASE if rule.params.get("ignore_case") else 0
    rx = re.compile(pattern, flags)
    target = tool.lower()
    for i, ev in enumerate(transcript.events):
        if ev.kind != EventKind.TOOL_CALL:
            continue
        if _tool_name(ev).lower() != target:
            continue
        if arg:
            haystack = str(_extract_arg(ev, arg))
        else:
            haystack = _flatten(ev.data) + " " + ev.content
        m = rx.search(haystack)
        if m:
            yield _violation(rule, ev, i, evidence=_snippet(haystack, m))


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
    phrases_raw = rule.params.get("consent_phrases") or rule.params.get("phrases")
    if not phrases_raw:
        raise ValueError(f"{rule.id}: require_consent requires `consent_phrases`")
    if isinstance(phrases_raw, str):
        phrases_raw = [phrases_raw]
    phrases = [p.lower() for p in phrases_raw]
    scoped_tool = rule.params.get("tool")
    scoped_tool = scoped_tool.lower() if isinstance(scoped_tool, str) else None
    arg = rule.params.get("arg")
    trigger_pattern = rule.params.get("trigger_pattern")
    trigger_rx = re.compile(trigger_pattern) if trigger_pattern else None

    consent_seen = False
    for i, ev in enumerate(transcript.events):
        if ev.kind == EventKind.MESSAGE and ev.actor == "user":
            text = ev.content.lower()
            if any(p in text for p in phrases):
                consent_seen = True
        elif ev.kind == EventKind.TOOL_CALL:
            if scoped_tool and _tool_name(ev).lower() != scoped_tool:
                continue
            if trigger_rx is not None:
                haystack = (
                    str(_extract_arg(ev, arg)) if arg else _flatten(ev.data)
                )
                if not trigger_rx.search(haystack):
                    continue
            if not consent_seen:
                yield _violation(
                    rule,
                    ev,
                    i,
                    evidence=f"tool_call without consent: {_tool_name(ev)}",
                )


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
    for i, ev in enumerate(transcript.events):
        if ev.kind not in kinds:
            continue
        haystack = ev.content + "\n" + _flatten(ev.data)
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
register("tool_arg_pattern", _eval_tool_arg_pattern)
register("require_consent", _eval_require_consent)
register("forbid_actor", _eval_forbid_actor)
register("max_tool_calls", _eval_max_tool_calls)
register("no_secret_in_output", _eval_no_secret_in_output)
