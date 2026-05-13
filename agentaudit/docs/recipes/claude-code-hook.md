# Recipe: live-block Claude Code tool calls with `agentaudit watch`

This recipe wires `agentaudit watch` into a Claude Code project as a
`PreToolUse` hook. The result: every tool call the agent attempts is
evaluated against the bundled defensive specs *before* it executes,
and any call matching a critical/high-severity rule is blocked and
recorded.

This is a defensive control. It is not a substitute for spec design
or for the existing `agentaudit check` post-hoc audit; treat it as a
last line of defense against the agent silently going off-script.

## Prereqs

```bash
pip install agentaudit
agentaudit --version   # confirm install
```

## Wire the hook

Create `.claude/hooks/pre-tool-use.sh` in your project (Claude Code's
runtime invokes this once per tool call, with the tool-call event as
JSON on stdin):

```bash
#!/usr/bin/env bash
# Pre-tool-use hook: ask agentaudit whether this tool call should
# proceed. Exit non-zero blocks the call.
set -euo pipefail

HIST="${CLAUDE_PROJECT_DIR:-.}/.claude/agentaudit-history.jsonl"
LOG="${CLAUDE_PROJECT_DIR:-.}/.claude/agentaudit-violations.jsonl"

# Feed the tool-call event on stdin; agentaudit decides allow/block.
# --history-file persists prior hook events across invocations.
# In this bare PreToolUse recipe, that history contains tool-call
# events only; it does NOT ingest user messages by itself.
exec agentaudit watch \
    --mode hook \
    --bundled-specs cli-safe \
    --block-severity high \
    --history-file "${HIST}" \
    --log-file "${LOG}"
```

Make it executable:

```bash
chmod +x .claude/hooks/pre-tool-use.sh
```

Register it in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/pre-tool-use.sh" }
        ]
      }
    ]
  }
}
```

> The `matcher: "Bash"` clause scopes the hook to Bash tool calls.
> The current bundled specs are Bash-scoped; if you add Edit/Write
> variants later, broaden the matcher accordingly.

Important boundary: this recipe wires only Claude Code's `PreToolUse`
hook. So `agentaudit` sees attempted Bash tool calls, but it does not
see user messages unless you add a separate ingestion path that records
them into `--history-file`. The hook is therefore immediately useful
for unconditional block rules, while consent-gated rules fail closed by
default rather than silently allowing risky operations.

## What gets blocked

With `--bundled-specs cli-safe` and `--block-severity high`, every
cross-deployment deterministic spec in the bundled library is
loaded. As of v0.3.0 that includes:

| spec                                          | catches                                       |
| --------------------------------------------- | --------------------------------------------- |
| `no-shell-without-confirm`                    | `rm -rf /`, force-push to main, `--no-verify` |
| `no-network-exfil`                            | unapproved curl/wget, `curl … \| sh`, netcat   |
| `no-secret-leak` / `no-pii-exfil`             | leak in tool result content                   |
| `no-pkg-install-without-confirm`              | silent `pip install`, `npm install`, …        |
| `no-credential-store-write`                   | writes to `~/.aws/credentials`, `~/.ssh/*`, … |
| `no-runtime-config-write-without-confirm`     | writes to `.git/hooks/`, `.github/workflows/`, `.claude/`, … |
| `no-instruction-file-write-without-confirm`   | writes to `CLAUDE.md`, `AGENTS.md`, `system-prompt.*`, … |

In this specific bare `PreToolUse` recipe:

* unconditional rules fire normally right away (`no-rm-rf-root`,
  `no-force-push-main`, `no-skip-hooks`, `no-network-exfil`,
  `no-credential-store-write`, and the output-content checks)
* `require_consent` rules remain *fail-closed* unless something else
  records user-message events into `--history-file`

So commands gated by explicit approval (`pip install ...`, writes into
`.git/hooks/` / `.github/workflows/` / `.claude/`, writes into
`CLAUDE.md` / `AGENTS.md`, and the high-risk shell operations covered
by `destructive-shell-needs-consent`) will still block by default in
this recipe even if the user previously said "yes" in the chat. To make
those rules honor approvals, add a second ingestion path that records
user messages into the history file, or load a narrower spec set that
excludes the consent-gated rules.

## What you'll see

On an allowed call:

```json
{"action": "allow", "event_index": 4, "reason": "no blocking violations", "violations": []}
```

(Exit code 0 — Claude Code proceeds with the tool call.)

On a blocked call:

```json
{
  "action": "block",
  "event_index": 4,
  "reason": "blocked by 1 rule(s) at or above high: no-rm-rf-root",
  "violations": [
    {
      "rule_id": "no-rm-rf-root",
      "rule_name": "forbid `rm -rf` on the filesystem root or home",
      "severity": "critical",
      "event_index": 4,
      "actor": "assistant",
      "evidence": "rm -rf /",
      "rationale": "A bare `rm -rf /` or `rm -rf ~` …"
    }
  ]
}
```

(Exit code 1 — Claude Code refuses to run the tool call. The agent
sees the failure and typically asks the user for guidance instead of
retrying.)

The full decision history is appended to
`.claude/agentaudit-violations.jsonl` for later review.

## Tuning

* **Quiet a noisy rule.** Drop `--bundled-specs cli-safe` and list
  individual specs you want, or fork the noisy spec and tune its
  pattern in place.
* **Keep the first hook deployment simple.** If you do not yet have a
  way to write user messages into `--history-file`, consider an
  explicit non-consent subset first (`no-network-exfil`,
  `no-secret-leak`, `no-pii-exfil`, `no-credential-store-write`) and
  add the consent-gated specs once you have a full transcript path.
* **Allow medium-severity findings to log without blocking.** Default
  `--block-severity high` already does this for medium/low. Set
  `--block-severity critical` if you want only the very worst things
  blocked.
* **Persist what the agent *attempted* even when blocked.** Add
  `--persist-blocked-events`. Useful for forensics; do NOT use if
  you want the history file to reflect only what actually ran.
* **Add custom site-specific rules.** Point `--spec` at additional
  markdown files alongside `--bundled-specs`; the union of all loaded
  rules applies.

## Caveats

* This is a Bash-tool-only first cut. The bundled v0.3.0 specs are
  Bash-scoped; Edit/Write tool variants are a v0.4.x candidate. Until
  then, an agent that bypasses Bash entirely (writing directly via
  the Edit tool) bypasses these specs.
* Fail-closed on malformed input: if the hook receives garbage on
  stdin, it returns block (exit 2). That means a broken pipe blocks
  every tool call — be ready to disable the hook quickly if it
  misbehaves (`mv .claude/settings.json .claude/settings.json.off`).
* Hook latency is the cost of every tool call. Bundled specs are
  fast deterministic regex; expect <50 ms per call on commodity
  hardware. Judge-backed specs (`--bundled-specs all`) call out to
  an LLM and add 1-5 s per call — not recommended for `watch`.
