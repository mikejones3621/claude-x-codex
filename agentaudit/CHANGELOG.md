# Changelog

All notable changes to `agentaudit` are documented here.

This project follows [Semantic Versioning](https://semver.org/) and the
keep-a-changelog format.

## [Unreleased]

### Added
- `examples/openai-agents-wrapped-good.json` - clean transcript shaped
  the way the real OpenAI Agents SDK emits run items (`message_output_item`,
  `tool_call_item`, `tool_call_output_item`, `reasoning_item` with
  `raw_item` payloads). Gives users a worked example of the wrapped-item
  ingestion path, complementing the unit-level adapter test.
- `specs/openai-agents/fabricated-system-messages.md` - deterministic
  defense against prompt injection that impersonates a higher-priority
  system or developer instruction from inside tool output. Three rules:
  a critical hard-fail for any `tool_result` normalized as `actor=system`,
  a high-severity pattern rule covering four families of fake authority
  claims (line-anchored `SYSTEM:` / `**Developer**:` / `### SYSTEM:` with
  markdown framing, chat-template tokens like `<|im_start|>system`, JSON
  `"role":"system"` injection, and bracketed labels like `[ADMIN]` or
  `[ALERT]`), and a medium-severity rule for the related
  assistant-impersonation attack (`Assistant: ignore the policy ...`).
- `examples/openai-agents-fabricated-system.json` plus end-to-end tests
  proving the bundled fabricated-system-message spec fires on a real
  OpenAI Responses envelope across three different injection framings
  (canonical `SYSTEM:` form, bracketed `[ADMIN]` form, and
  assistant-impersonation form), and on the canonical `tool_result` +
  `actor=system` edge case. A separate negative test asserts the spec
  does not false-positive on documentation-style content that mentions
  the same trigger words in benign context.
- CI dogfood step asserts the fabricated-system fixture exits non-zero
  under the bundled fabricated-system spec, so the contract is in CI.
- New end-to-end test exercising the wrapped fixture against every
  bundled spec under `specs/**/*.md` (with a no-op judge for judge-backed
  rules), proving the `raw_item`/`item` unwrap path flows cleanly through
  the rule engine, not just the adapter.

### Hardened (fabricated-system spec, two adversarial passes)
- First pass (codex) closed three obfuscation classes: zero-width
  separators inside `SYSTEM`, fullwidth colon `：`, and JSON `role:system`
  payloads with polite filler before the trigger verb.
- Second pass (claude) closed four more bypass classes that survived the
  first pass: zero-width separators inside `developer`, alternative
  separators (`#`, `=`, `|`), and a new fifth regex alternative for
  multi-line label-then-trigger attacks (`### SYSTEM\n...ignore...`)
  with a deliberately tightened trigger verb set to avoid
  false-positives on legitimate `## Developer` / `## System` documentation.
- A documented known limitation (homoglyph obfuscation: fullwidth Latin
  letters and Cyrillic look-alikes) is pinned in a regression test so
  whoever lands NFKC normalisation at the rule layer will know to flip
  the assertion. 25 tests total; CI dogfood unchanged.

## [0.1.0] - 2026-05-04

Initial public release. Built collaboratively by Claude (Anthropic) and
Codex (OpenAI) as a cross-lab AI-safety artifact.

### Added
- Canonical `Transcript` / `Event` schema with four event kinds
  (`message`, `tool_call`, `tool_result`, `reasoning`).
- Adapters for Claude Code session JSONL, OpenAI Responses / Agents SDK
  (bare list, JSONL, `output`-wrapped envelope, and `raw_item` / `item`
  wrapped runner items), and a generic native-schema loader.
- Markdown spec format with `agentaudit` fenced rule blocks; rule body
  text is preserved as the rationale shown in violation reports.
- Ten built-in deterministic rule types: `forbid_pattern`,
  `require_pattern`, `forbid_tool`, `allowlist_tool`, `tool_arg_pattern`,
  `require_consent` (with optional `trigger_pattern` and one-shot vs.
  persistent consent), `forbid_actor`, `max_tool_calls`,
  `no_secret_in_output`, and a `judge` rule type for caller-supplied
  fuzzy review.
- Bundled credential pattern pack covering AWS, GitHub, OpenAI,
  Anthropic, Slack, generic high-entropy assignments, and PEM private
  keys.
- Reference spec library: `no-secret-leak.md`, `no-shell-without-confirm.md`,
  `no-network-exfil.md`, `no-pii-exfil.md`, plus
  `openai-agents/tool-allowlist.md` and
  `openai-agents/prompt-injection-resistance.md`.
- CLI: `agentaudit check` (text or JSON output, severity-gated exit
  code, optional adapter selection) and `agentaudit list-rules`.
- Worked examples: clean and dirty canonical transcripts, a clean
  OpenAI Responses envelope, and a dirty OpenAI Responses envelope that
  exfiltrates a key through a non-allowlisted tool.
- Pluggable judge interface via `check(..., judge=...)`; judge can yield
  `Violation`, `JudgeFinding`, or plain dicts.
- 17 tests covering spec parsing, adapter normalisation across formats,
  every rule type, severity ordering, consent edge cases, the judge
  hook, and an end-to-end OpenAI Agents exfil scenario.
- GitHub Actions workflow that runs the test suite on Python 3.10-3.12
  and dogfoods `agentaudit check` on the bundled fixtures so a
  regression in the CLI exit-code contract fails CI.
