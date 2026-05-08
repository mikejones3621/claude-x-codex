# Changelog

All notable changes to `agentaudit` are documented here.

This project follows [Semantic Versioning](https://semver.org/) and the
keep-a-changelog format.

## [Unreleased]

### Added
- `examples/openai-agents-wrapped-good.json` — clean transcript shaped
  the way the real OpenAI Agents SDK emits run items (`message_output_item`,
  `tool_call_item`, `tool_call_output_item`, `reasoning_item` with
  `raw_item` payloads). Gives users a worked example of the wrapped-item
  ingestion path, complementing the unit-level adapter test.
- New end-to-end test exercising the wrapped fixture against every
  bundled spec under `specs/**/*.md` (with a no-op judge for judge-backed
  rules), proving the `raw_item`/`item` unwrap path flows cleanly through
  the rule engine, not just the adapter (18 tests total).

## [0.1.0] — 2026-05-04

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
- GitHub Actions workflow that runs the test suite on Python 3.10–3.12
  and dogfoods `agentaudit check` on the bundled fixtures so a
  regression in the CLI exit-code contract fails CI.
