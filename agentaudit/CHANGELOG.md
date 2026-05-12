# Changelog

All notable changes to `agentaudit` are documented here.

This project follows [Semantic Versioning](https://semver.org/) and the
keep-a-changelog format.

## [Unreleased]

### Changed
- CLI auto-detection now recognizes Anthropic Messages worked-example
  filenames (`anthropic*`, `*messages*`) and routes them through the
  `anthropic_messages` adapter automatically, mirroring the existing
  filename-hint path for Claude Code and OpenAI examples.
- CI dogfood now runs `agentaudit check` against the bundled
  `examples/anthropic-messages-good.json` fixture across the bundled
  cross-lab deterministic specs, so the Anthropic adapter is exercised
  by the same command-line contract we already enforce for the generic
  and OpenAI examples.
- Added `examples/anthropic-messages-bad.json` plus an end-to-end test
  and CI dogfood step proving Anthropic-shaped transcripts trip the same
  fabricated-authority and secret-leak specs as the OpenAI fixtures.
- JSON report output now includes top-level `ok` and `summary`
  fields (`total` plus `by_severity`) so CI and downstream tooling can
  consume aggregate result status without re-counting the violations
  array client-side.

## [0.2.0] - 2026-05-08

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

### New adapter — Anthropic Messages API
- `agentaudit/adapters/anthropic_messages.py` accepts the canonical
  Anthropic Messages API conversation-history shape: request envelope
  (`{"messages": [...]}`), bare list, response envelope (single
  assistant turn), or JSONL. Handles text / thinking / tool_use /
  tool_result blocks; tool_use becomes `tool_call` events with
  `actor=assistant`, tool_result becomes `tool_result` events with
  `actor=tool` (matching the existing claude_code convention so rules
  written against `actor="tool"` apply unchanged).
- `examples/anthropic-messages-good.json` worked fixture.
- 12 unit tests in `test_anthropic_messages_adapter.py` covering all
  four input shapes, every block type, the `is_error` flag,
  unknown-block-type silent-drop, and an end-to-end pass against the
  bundled cross-lab spec set.

### Architectural — `normalize` parameter for pattern rules
- New `agentaudit.text` module exposes `normalize_for_match(content, level)`.
  Levels: `false`/`None` (no-op), `true`/`"basic"` (NFKC + zero-width strip),
  `"strict"` (basic + curated Cyrillic→Latin homoglyph fold). Unknown levels
  raise loudly so a typo in a spec cannot silently disable the protection.
- `forbid_pattern`, `require_pattern`, `tool_arg_pattern`, and
  `no_secret_in_output` all read `normalize = ...` from the rule and apply
  that normalisation to the matched haystack before regex evaluation. Tool
  name lookups (`forbid_tool` / `allowlist_tool` / `require_consent`) are
  intentionally not normalised — agent runtimes typically forbid weird
  characters in tool names, so the practical attack surface is the rule
  arguments and free-text content, both of which are now covered.
- The bundled `fabricated-system-messages.md` spec opts into
  `normalize = "strict"`, which lets us delete the inline zero-width
  character classes from the pattern (recovering readability) while
  *gaining* coverage of fullwidth Latin (`ＳＹＳＴＥＭ`) and Cyrillic
  homoglyph (`ЅYSTEM`, `ЅYЅTЕМ`) attacks. The previously-pinned "known
  limitation" test is now a positive assertion that those cases trigger.
- 16 new unit tests for `normalize_for_match` lock in NFKC behaviour,
  zero-width stripping, the strict-mode fold table, and the unknown-level
  error path.

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
