"""agentaudit / openai_agents_hook.py — reference integration for the
OpenAI Agents SDK.

Wires `agentaudit.evaluate_event` into an OpenAI Agents pre-tool-call
hook so every tool call is evaluated against your loaded specs and
blocked when a high-severity rule fires.

This file is reference code, not a runtime dependency. Copy it into
your project, point it at your spec set, and register
`pre_tool_call_block` (or whichever name your SDK version expects) as
your hook callback.

The integration shape:

    from agents import Agent, RunHooks  # SDK names vary by version
    from agentaudit_hook import build_agentaudit_hook

    hook = build_agentaudit_hook(
        spec_paths=[
            "specs/no-shell-without-confirm.md",
            "specs/no-credential-store-write.md",
            "specs/no-cross-agent-injection.md",
            # ... add the specs that matter to your deployment
        ],
        history_path=".agentaudit/history.jsonl",
        block_severity="high",
    )

    agent = Agent(..., hooks=RunHooks(before_tool_call=hook))

When a hook fires `AgentauditBlocked`, the SDK should surface it to
the agent as a tool-call failure. The agent typically asks the user
for guidance rather than retrying.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from agentaudit import (
    Decision,
    Event,
    EventKind,
    Spec,
    evaluate_event,
    load_spec,
    read_history,
)
from agentaudit.watch import append_history, append_log


class AgentauditBlocked(Exception):
    """Raised when agentaudit decides a tool call must not proceed.

    The OpenAI Agents SDK surfaces the exception as a tool-call
    failure to the agent. Catch this in your own outer try/except if
    you want to log differently or short-circuit the run.
    """

    def __init__(self, decision: Decision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass
class _AgentauditHook:
    """Internal state holder for the hook callable.

    Built by `build_agentaudit_hook`. You normally don't construct
    this directly.
    """

    specs: list[Spec]
    history_path: Path | None
    log_path: Path | None
    block_severity: str
    actor_name: str
    persist_blocked_events: bool

    def __call__(self, tool_call: Any) -> None:
        event = _tool_call_to_event(tool_call, actor=self.actor_name)
        history = read_history(self.history_path) if self.history_path else []
        decision = evaluate_event(
            history, event, self.specs, block_severity=self.block_severity
        )
        if self.log_path is not None:
            append_log(self.log_path, decision)
        if decision.action == "block":
            if self.history_path is not None and self.persist_blocked_events:
                append_history(self.history_path, event)
            raise AgentauditBlocked(decision)
        if self.history_path is not None:
            append_history(self.history_path, event)


def build_agentaudit_hook(
    spec_paths: Iterable[str | Path],
    *,
    history_path: str | Path | None = None,
    log_path: str | Path | None = None,
    block_severity: str = "high",
    actor_name: str = "assistant",
    persist_blocked_events: bool = False,
) -> Callable[[Any], None]:
    """Return a callable suitable for use as an OpenAI Agents hook.

    The callable signature matches the SDK's `before_tool_call`
    contract: it takes a single object describing the impending tool
    call and either returns `None` (allow) or raises
    `AgentauditBlocked` (block).
    """
    specs = [load_spec(p) for p in spec_paths]
    return _AgentauditHook(
        specs=specs,
        history_path=Path(history_path) if history_path else None,
        log_path=Path(log_path) if log_path else None,
        block_severity=block_severity,
        actor_name=actor_name,
        persist_blocked_events=persist_blocked_events,
    )


def _tool_call_to_event(tool_call: Any, *, actor: str) -> Event:
    """Convert an OpenAI Agents tool-call object into an agentaudit Event.

    The SDK's tool-call object shape has evolved across versions; this
    helper attempts the common attribute names. If your SDK version
    differs, replace this helper with one that maps your fields.
    """
    # Common shapes seen in OpenAI Agents SDK 0.x/1.x:
    #   tool_call.tool_name        / tool_call.name
    #   tool_call.arguments         / tool_call.input / tool_call.args
    name = (
        getattr(tool_call, "tool_name", None)
        or getattr(tool_call, "name", None)
        or getattr(tool_call, "tool", None)
        or "<unknown>"
    )
    raw_args = (
        getattr(tool_call, "arguments", None)
        or getattr(tool_call, "input", None)
        or getattr(tool_call, "args", None)
        or {}
    )
    # Arguments may be a JSON string or a dict, depending on version.
    if isinstance(raw_args, str):
        try:
            args_dict = json.loads(raw_args)
        except json.JSONDecodeError:
            args_dict = {"_raw": raw_args}
    elif isinstance(raw_args, dict):
        args_dict = raw_args
    else:
        args_dict = {"_raw": str(raw_args)}

    return Event(
        kind=EventKind.TOOL_CALL,
        actor=actor,
        content="",
        data={"name": name, "input": args_dict},
    )
