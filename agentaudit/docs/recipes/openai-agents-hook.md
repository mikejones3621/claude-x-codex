# Recipe: live-block OpenAI Agents tool calls with `agentaudit`

This recipe wires `agentaudit` into an OpenAI Agents SDK
deployment as a pre-tool-call hook. Every tool call the agent
attempts is evaluated against the bundled defensive specs *before*
it executes, and any call matching a critical/high-severity rule
raises `AgentauditBlocked` — which the SDK surfaces to the agent as
a tool-call failure.

This is the OpenAI-Agents-side companion to
[`claude-code-hook.md`](claude-code-hook.md). The defensive specs
are the same on both sides; the integration point is what differs.

## Prereqs

```bash
pip install agentaudit
pip install openai-agents   # or whichever SDK package you're on
```

## Drop in the hook module

Copy [`recipes/openai_agents_hook.py`](../../recipes/openai_agents_hook.py)
to your project. It's reference code, not a runtime dependency —
you'll typically vendor it next to your agent definition.

```bash
cp $(python -c "import agentaudit, pathlib; print(pathlib.Path(agentaudit.__file__).parent.parent.parent / 'recipes' / 'openai_agents_hook.py')") \
    my_project/agentaudit_hook.py
```

(Or just open the file in this repo and paste — it's < 200 lines.)

## Register it

```python
from agents import Agent, RunHooks  # SDK names vary by version
from agentaudit_hook import build_agentaudit_hook, AgentauditBlocked

hook = build_agentaudit_hook(
    spec_paths=[
        # Cross-deployment deterministic — same set the CLI's
        # --bundled-specs cli-safe loads.
        "specs/no-secret-leak.md",
        "specs/no-shell-without-confirm.md",
        "specs/no-network-exfil.md",
        "specs/no-pii-exfil.md",
        "specs/no-pkg-install-without-confirm.md",
        "specs/no-credential-store-write.md",
        "specs/no-runtime-config-write-without-confirm.md",
        "specs/no-instruction-file-write-without-confirm.md",
        "specs/no-cross-agent-injection.md",
    ],
    history_path=".agentaudit/history.jsonl",
    log_path=".agentaudit/violations.jsonl",
    block_severity="high",
    actor_name="assistant",
)

agent = Agent(
    name="researcher",
    instructions=...,
    tools=[...],
    hooks=RunHooks(before_tool_call=hook),
)
```

If the SDK version you're on uses a different hook name, adapt:
`before_tool_call`, `pre_tool_call`, `on_tool_call_start`, etc. —
the callable contract `build_agentaudit_hook` returns is
`hook(tool_call) -> None | raises AgentauditBlocked`.

## Closing the consent gap (user-input hook)

Just like the Claude Code recipe, the bare tool-call hook only sees
tool calls. `require_consent` rules looking back at history for "yes,
install it" won't find it unless you also wire a user-input hook that
records user messages into the same history file.

```python
from agentaudit_hook import (
    build_agentaudit_hook,
    build_agentaudit_user_input_hook,
)

HISTORY = ".agentaudit/history.jsonl"

tool_hook = build_agentaudit_hook(
    spec_paths=[...],
    history_path=HISTORY,
    block_severity="high",
)
ui_hook = build_agentaudit_user_input_hook(HISTORY)

agent = Agent(
    name="researcher",
    instructions=...,
    tools=[...],
    hooks=RunHooks(
        before_tool_call=tool_hook,
        before_user_input=ui_hook,   # SDK name varies — adapt to your version
    ),
)
```

The user-input hook accepts plain strings, dicts with
`content`/`text`/`message`/`prompt` fields, or objects with
`.content` / `.text` attributes. With both hooks wired, the
`require_consent` rules clear when the user explicitly approves in
chat — same as the dual-hook Claude Code deployment.

There's a unit test that pipes this exact scenario end-to-end:
`tests/test_recipes_openai_agents.py::test_user_input_hook_then_tool_hook_closes_consent_gap`.

## Multi-agent setups

The strongest reason to deploy this in an OpenAI Agents environment
is that OpenAI Agents *is* a multi-agent SDK. Tool results from one
sub-agent become context for another; that's exactly the
cross-actor propagation surface that
[`no-cross-agent-injection.md`](../../specs/no-cross-agent-injection.md)
exists to defend. See
[`docs/threat-models/multi-agent-injection.md`](../threat-models/multi-agent-injection.md)
for the threat model.

For multi-agent deployments, set distinct `actor_name`s when
constructing the hook for each sub-agent so the cross_actor
propagation rule has a real boundary to see:

```python
planner_hook = build_agentaudit_hook(
    spec_paths=[...],
    history_path=".agentaudit/shared-history.jsonl",  # shared!
    actor_name="agent:planner",
)
executor_hook = build_agentaudit_hook(
    spec_paths=[...],
    history_path=".agentaudit/shared-history.jsonl",
    actor_name="agent:executor",
)
```

Sharing the history path means the cross-actor rule sees BOTH
agents' events, and a directive originating in the planner's
output that gets parroted by the executor will fire.

## What you'll see

When a tool call is allowed, the hook returns silently — your agent
proceeds. When blocked:

```python
try:
    result = await agent.run(...)
except AgentauditBlocked as exc:
    decision = exc.decision
    # decision.action == "block"
    # decision.reason — short human-readable summary
    # decision.violations — list of Violation dicts with rule_id,
    #                       evidence, severity, etc.
    log_security_event(decision)
    raise
```

The full decision history is also written to
`.agentaudit/violations.jsonl` for later forensic review.

## Tuning

* **Reduce noise.** Drop any spec from `spec_paths` that produces
  false positives for your workflow. Or override `block_severity` to
  `critical` so only the worst things actually block (medium/high
  findings are still logged).
* **Cross-actor sensitivity.** If you run an agent that legitimately
  quotes directives from one source to another (security-research
  agent), narrow `no-cross-agent-injection.md`'s pattern or drop
  the spec.
* **Persist blocked events for forensics.** Pass
  `persist_blocked_events=True` to `build_agentaudit_hook` to keep
  a record of what the agent attempted even when blocked.

## Caveats

* **SDK version drift.** OpenAI Agents SDK is moving fast.
  `_tool_call_to_event` in the recipe attempts the common
  attribute names, but if your SDK version uses different field
  names, replace that helper to map your fields. It's <30 lines.
* **Async hooks.** If your SDK calls the hook asynchronously,
  wrap `_AgentauditHook.__call__` in an `async def` adapter — the
  underlying evaluation is pure CPU and won't deadlock.
* **Fail-closed posture.** The Python module raises
  `AgentauditBlocked` on block. It does *not* automatically
  fail-closed on internal errors — wrap the agent run in a
  try/except if you want a defensive "any agentaudit failure stops
  the agent" posture.
