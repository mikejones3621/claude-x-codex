# Security Policy

`agentaudit` is a defensive tool: it audits LLM agent transcripts and
blocks unsafe tool calls. We take the correctness of that blocking
seriously — a missed detection or a bypass is a security issue.

## Reporting a vulnerability

Please report suspected vulnerabilities privately rather than opening a
public issue:

- Use GitHub's **"Report a vulnerability"** flow under the repository's
  **Security** tab (private advisory), or
- email the maintainers at the address listed on the repository profile.

Include, where possible:

- the spec(s) and a minimal transcript or event that demonstrates the
  problem,
- the expected verdict vs. the observed verdict (e.g. "should block,
  allowed through"),
- the `agentaudit` version (`agentaudit --version`) and Python version.

We aim to acknowledge reports within a few business days.

## Scope

In-scope examples:

- a malicious transcript/event that **evades** a bundled spec that
  should catch it (a detection bypass),
- a crafted spec or input that causes the checker to **fail open**
  (allow an event it should block) or to crash in a way that a
  fail-closed deployment would treat as allow,
- a pattern that causes catastrophic backtracking (ReDoS) in rule
  evaluation.

Out of scope:

- weaknesses that require the operator to deliberately misconfigure
  `--block-severity` or to run with no specs,
- the behavior of the agent runtime itself (Claude Code, OpenAI Agents,
  etc.) outside `agentaudit`'s hook.

## Supported versions

This project is pre-1.0; security fixes land on the latest released
version. Please upgrade to the most recent version before reporting.
