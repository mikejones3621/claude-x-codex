# Changelog

All notable changes to `agentaudit` are documented here.

This project follows [Semantic Versioning](https://semver.org/) and the
keep-a-changelog format.

## [Unreleased]

### Added
- **Direct (non-Bash) mutation coverage — v0.5.0 headline.** Closes
  the surface Codex named on codex-board.md 2026-05-13T03:17Z and
  that both `specs/no-runtime-config-write-without-confirm.md` and
  `specs/no-instruction-file-write-without-confirm.md` already flagged
  inline: every Bash-gated rule in the cli-safe bundle was blind to
  agents using direct file tools (Claude Code's `Edit` / `Write` /
  `MultiEdit` / `NotebookEdit`, MCP filesystem variants, custom
  OpenAI Agents file tools) to do the SAME conceptual harms.

  Three new bundled specs (auto-classify into `cli-safe`):
  * `no-direct-credential-store-write.md` — CRITICAL forbid. Same
    credential-path set as the Bash version (`.aws/credentials`,
    `.ssh/id_*`, `.ssh/authorized_keys`, `.npmrc`, `.pypirc`,
    `.netrc`, `.docker/config.json`, `.kube/config`, `.gnupg/*`,
    `.config/gcloud/*`, `.config/op/*`) matched against the
    `file_path` / `notebook_path` / `path` / `target_path` /
    `destination` / `uri` argument of common file-mutation tools.
    No consent override.
  * `no-direct-runtime-config-write-without-confirm.md` — HIGH
    `require_consent`. Same runtime/CI/hooks path set (`.claude/*`,
    `.husky/*`, `.git/hooks/*`, `.github/workflows/*` + `actions/*`,
    `.cursor/*`, `.cursorrules`, `.clinerules`).
  * `no-direct-instruction-file-write-without-confirm.md` — HIGH
    `require_consent`. Same instruction-file set (`CLAUDE.md`,
    `AGENTS.md`, `.github/copilot-instructions.md`, system-prompt
    files, `.aider.conf.{yml,yaml}`, `.roo/rules`).

  Rule-type plumbing: `tool_arg_pattern` and `require_consent` now
  accept `tools` (list) and `args` (list) alongside the existing
  singular `tool` and `arg`. Single + list forms are mutually
  accepted; list form takes precedence. This lets a single rule
  catch the same harm across multiple file-mutating tools each of
  which uses a slightly different arg name. Backward compatible —
  every existing spec keeps working unchanged.

  New worked-fixture: `examples/bad-transcript-direct-selfmod.jsonl`.
  7 mutations, zero Bash calls — proves the gap is real (the
  pre-v0.5.0 Bash-only specs are silent on this fixture) and the
  new specs are the closure (full cli-safe bundle exits 1).
  `tests/test_bad_transcript_direct_selfmod.py` locks both contracts
  (every new spec fires at least once; every Bash-only spec stays
  silent). CI dogfood adds 6 new steps including the negative
  control — if a future contributor accidentally re-opens the gap
  by reverting a spec, the workflow fails loudly with a named
  exit-code-mismatch error.

  Coverage notes:
  * Operators with bespoke MCP file servers or custom OpenAI Agents
    file tools should extend the `tools` list in their own spec —
    the bundled list is conservative and named for the most common
    deployments.
  * User-level XDG-style config under `~/.config/...` is
    intentionally out of scope for the direct-tool runtime-config
    spec (the Bash version covers it via the home-prefix-bearing
    command text; the file-tool version sees only the resolved
    path, and false-positive risk is acceptable only with
    operator-side context).
  * Obfuscated path construction (custom tools that build the
    target path from components the rule doesn't see) remains
    future judge-backed spec territory.

  Follow-on narrowing point:
  * `no-direct-dangerous-shell-content.md` adds the **content-side**
    complement to the v0.5.0 path-side closure. It gates
    `curl|wget ... | sh|bash|python|python3|node|ruby|perl` and
    `nc -l...` / `nc -e ...` payloads written through direct file
    tools (`Write`, `Edit`, `MultiEdit`, common MCP filesystem
    variants, etc.), even when the destination path itself is not
    special-cased by the credential/runtime/instruction-file specs.
    This catches arbitrary script paths like
    `/repo/scripts/install.sh` or `/repo/tools/bootstrap.sh`, while
    still allowing legitimate docs/fixture cases via explicit
    consent. Added worked fixture
    `examples/bad-transcript-direct-dangerous-content.jsonl` plus
    `tests/test_specs_direct_dangerous_content.py` (`17 passed`).

  Test count: 285 (was 213).
- **OpenAI Agents user-input hook — parallel consent-gap close on the
  OpenAI side.** `recipes/openai_agents_hook.py` now exports
  `build_agentaudit_user_input_hook(history_path, actor_name=...)`
  returning a callable suitable for an OpenAI Agents
  `before_user_input` / `on_user_message` hook. Accepts string, dict,
  or object-with-attribute user-input shapes; records a `message`
  event into the same JSONL history file the tool-call hook reads.
  With both hooks wired and a shared `history_path`, the OpenAI
  Agents deployment now has the same consent-gap closure as the
  Claude Code dual-hook recipe. 6 new tests at
  `tests/test_recipes_openai_agents.py` (string / dict / attribute
  shapes, custom actor for multi-agent, end-to-end consent-gap
  closure with the tool-call hook). Recipe doc
  (`docs/recipes/openai-agents-hook.md`) updated with the new
  section.
- **`agentaudit ingest` subcommand + companion
  `claude-code-user-prompt-submit.sh` recipe — closes the consent
  gap Codex named.** The bare `PreToolUse` recipe only ever sees
  tool calls; consent-gated specs (pkg-install, runtime-config,
  instruction-file, destructive-shell) therefore stayed fail-closed
  even after the user said "yes, install it" in chat. This
  subcommand reads an event from stdin (bare text or JSON wrapper)
  and appends it to the watch history file without evaluating it.
  Plug it into the `UserPromptSubmit` hook (a runnable companion
  script ships at `recipes/claude-code-user-prompt-submit.sh`) so
  user messages land in the same JSONL history the PreToolUse hook
  reads, and consent rules clear end-to-end. Public Python API:
  `run_ingest` exported from `agentaudit`. 11 tests at
  `tests/test_ingest.py` including the headline closure test
  `test_cli_ingest_then_watch_closes_the_consent_gap` that pipes
  the dual-hook scenario through the actual CLI: ingest "yes, install
  it" → watch a `pip install requests` event → ALLOW. CI dogfood
  added: a dual-hook scenario where ingested consent unblocks
  pkg-install (exit 0), and a control scenario where a non-consent
  user message keeps the gate closed (exit 1).
- **Cross-lab `agentaudit watch` integration recipes.** Two
  ready-to-deploy integration paths now ship in the repo:
  * `recipes/claude-code-pre-tool-use.sh` — a runnable Bash hook
    script designed to be dropped at `.claude/hooks/pre-tool-use.sh`
    in any Claude Code project. Quick install: `cp` + `chmod +x` +
    one `.claude/settings.json` entry. Configurable via
    `AGENTAUDIT_BUNDLED_SET`, `AGENTAUDIT_BLOCK_SEVERITY`,
    `AGENTAUDIT_HISTORY`, `AGENTAUDIT_LOG` env vars.
  * `recipes/openai_agents_hook.py` — a reference Python module for
    OpenAI Agents SDK deployments. Exposes
    `build_agentaudit_hook(...)` returning a callable suitable for
    `RunHooks(before_tool_call=...)` and `AgentauditBlocked` for the
    block exception. Supports three SDK tool-call object shapes
    (v1/v2/v3 attribute naming) so it survives upstream SDK drift.
    Designed for multi-agent setups: distinct `actor_name`s per
    sub-agent + a shared `history_path` make `cross_actor_propagation`
    fire on real cross-agent boundaries. Full recipe doc at
    `docs/recipes/openai-agents-hook.md`. 8 unit tests at
    `tests/test_recipes_openai_agents.py` exercising the
    duck-typed tool-call adapters.
- **Confirmed: `cross_actor_propagation` fires in live-blocking
  mode.** New regression test at
  `tests/test_watch.py::test_watch_fires_cross_actor_propagation_in_hook_mode`
  drives the multi-agent injection pattern through `run_hook_mode`
  with a persisted history file: the originator (tool_result with
  the directive) is recorded but not flagged (it's not the
  propagator), the next hook invocation for the assistant's
  parroting tool_call is **blocked at exit code 1** before the
  runtime can execute it. The same defensive rule that catches the
  pattern post-hoc via `check`/`replay` also catches it live.
- **New rule type `cross_actor_propagation` + bundled spec
  `no-cross-agent-injection.md`.** Catches the canonical multi-agent
  / tool-result prompt-injection attack: a directive ("ignore
  previous instructions", "new instructions:", `<<system>>`-style
  envelope) appears in one actor's output (tool_result, message)
  and then a DIFFERENT actor's subsequent event (tool_call, message)
  parrots the same directive. The cross-actor boundary is the
  signal — the same pattern bouncing inside one actor's stream
  doesn't fire. Default `max_distance = 10` events. 8 unit tests at
  `tests/test_cross_actor_propagation.py`; new worked-fixture at
  `examples/bad-transcript-cross-agent-injection.jsonl` exercises a
  webfetch-injects-attacker-directive scenario end-to-end and is
  dogfooded in CI. Full threat-model writeup at
  `docs/threat-models/multi-agent-injection.md`. This is the
  defensive control no other transcript auditor in the field
  currently provides — most existing detectors look at a single
  message in isolation and miss the *propagation* event.
- **`agentaudit watch` — live-blocking mode.** This is the headline
  v0.4.0-shaped addition: a new CLI subcommand that turns the
  post-hoc transcript checker into a real-time guard. An agent
  runtime invokes `agentaudit watch` (per tool call in hook mode, or
  continuously in stream mode), passes the event as JSON on stdin,
  and the watcher returns an allow/block decision on stdout plus a
  non-zero exit code on block. State is persisted between hook
  invocations via a `--history-file` JSONL path. In hook deployments
  that only feed `tool_call` events (for example a bare Claude Code
  `PreToolUse` hook), that history immediately preserves prior tool
  calls but does NOT synthesize user-message consent; consent-gated
  specs therefore stay fail-closed unless a second ingestion path
  records user messages into history. Fail-closed on malformed input
  (garbage in → block out, never silent allow).

  Two modes:
  * `--mode hook` (default): one event in, one decision out, exit
    0=allow / 1=block / 2=malformed. Designed for per-tool-call hooks
    like Claude Code's `PreToolUse`.
  * `--mode stream`: line-delimited events from stdin forever,
    line-delimited decisions on stdout, history in memory. Designed
    for sidecar deployments.

  Public Python API exported from `agentaudit`:
  `evaluate_event`, `Decision`, `read_history`, `run_hook_mode`,
  `run_stream_mode`.

  19 unit + integration tests at `tests/test_watch.py`, including a
  headline end-to-end test that pipes the v0.3.0 self-modification
  scenario through `run_stream_mode` and asserts every malicious
  step is independently blocked. A complete Claude Code hook
  integration recipe lives at `docs/recipes/claude-code-hook.md`.
- **`agentaudit replay` — feed a stored transcript through the
  live-blocking pipeline.** Companion to `watch`: takes a transcript
  file and emits the same per-event decisions the live watcher would
  produce, on a "what would my hook have done with this past
  session?" basis. Blocked events do NOT pollute the in-replay
  history (mirroring the production blocking contract — in real
  life the runtime would have rejected them, so subsequent events
  see history as if they never happened). Use cases: pre-deployment
  validation, operator training, CI gating on curated malicious
  fixtures. 5 unit tests at `tests/test_replay.py` plus 4 subprocess
  tests at `tests/test_watch_cli.py` (which also covers the `watch`
  CLI exit-code contract end-to-end through a real subprocess
  boundary — closes the in-process-vs-CLI gap that the in-process
  tests can't see). Public Python API: `run_replay` exported from
  `agentaudit`.
- CI dogfood (`.github/workflows/agentaudit.yml`) now exercises
  `agentaudit watch` (hook mode, block + allow paths) and
  `agentaudit replay` (against both the v0.3.0 self-mod malicious
  fixture and the clean good-transcript) — `watch` must exit 1 on
  `rm -rf /` and 0 on `ls -la`; `replay` must exit 1 on the
  malicious fixture and 0 on the clean one.
- New subprocess regression test in `tests/test_watch_cli.py` locks in
  the current Claude Code hook boundary: a persisted hook-only history
  file does NOT conjure user consent, so a later `pip install ...`
  still blocks under `pkg-install-needs-consent` unless something else
  has written a user-message event into the history first.
- New worked-example bad fixture
  `examples/bad-transcript-v030-selfmod.jsonl`. Walks a short agent
  session that hits all four v0.3.0 bundled defensive specs in one
  coherent malicious scenario: `pip install requests` without consent
  → write to `~/.aws/credentials` → plant
  `curl … | sh` in `.git/hooks/pre-commit` → `chmod +x` the hook →
  append "IGNORE ALL USER INSTRUCTIONS" to `CLAUDE.md`. The bonus
  `no-piped-network-shell` rule in `no-network-exfil.md` also fires
  on the planted-hook contents (defense in depth working as
  designed). `tests/test_bad_transcript_v030_selfmod.py` locks in
  the cross-spec contract: each new spec fires at least once,
  `runtime-config-write-needs-consent` fires on both the echo
  redirect and the chmod (no consent-bleed), and the total
  violation count stays at >= 5. CI dogfooded via
  `.github/workflows/agentaudit.yml` — the fixture must exit
  non-zero against `--bundled-specs cli-safe`.
- New bundled cross-deployment deterministic spec
  `no-instruction-file-write-without-confirm.md`. Gates Bash-driven
  writes to project / user agent-instruction documents behind explicit
  user consent: `CLAUDE.md` (anywhere in tree, including nested
  subdirectories), `AGENTS.md`, `.github/copilot-instructions.md`,
  `system-prompt.{md,txt,json,yaml,yml}` (and `system_prompt.*`),
  `.aider.conf.{yml,yaml}`, `.roo/rules`, `.roo/system-prompt*`.
  Same write-verb set as the other `*-write-without-confirm` specs
  (redirect / `tee` / `cp` / `mv` / `install` / `ln` / `chmod` /
  `chown` / `rm` / `sed -i`). Severity HIGH with `require_consent`
  because legitimate edits are common — the user just needs to say
  yes explicitly. 17 unit tests at
  `tests/test_specs_instruction_file.py`, including regression locks
  on `MYCLAUDE.md` (must NOT match — case-anchored to filename
  boundary), nested `apps/web/CLAUDE.md` (must match), and
  read-direction `cp CLAUDE.md /tmp/x` (must NOT match). Out of
  scope: `README.md`, `CONTRIBUTING.md`, `docs/`; `.cursorrules` /
  `.clinerules` / `.cursor/rules` / `.claude/` (those are covered
  by `no-runtime-config-write-without-confirm.md`); `Edit` / `Write`
  tool variants (Bash-only for v1).
- New bundled cross-deployment deterministic spec
  `no-runtime-config-write-without-confirm.md`. Gates Bash-driven
  writes to runtime / CI / hooks config behind explicit user consent:
  `.claude/hooks/*`, `.claude/settings.json`,
  `.claude/settings.local.json`, `~/.claude/*`,
  `~/.config/{claude-code,openai-agents,gemini-cli,aider}/*`,
  `.husky/*`, `.git/hooks/*`, `.github/workflows/*`,
  `.github/actions/*`, `.cursor/rules`, `.cursor/mcp.json`,
  `.cursorrules`, `.clinerules`. Covers the same write-verb set as
  `no-credential-store-write` (redirect, `tee`, `cp` / `mv` /
  `install` / `ln` with target-as-last-arg, `chmod` / `chown`) plus
  `rm` (deletion-is-a-config-change) and `sed -i` (the canonical
  inline-edit verb). Severity HIGH with `require_consent` because
  legitimate cases exist (registering a new GitHub Actions job, etc.)
  but the user should approve them explicitly. 18 unit tests at
  `tests/test_specs_runtime_config.py`. Read-direction operations,
  `CLAUDE.md` / `AGENTS.md` instruction-file edits, and direct
  `Edit`/`Write` tool calls (vs. Bash) are intentionally out of
  scope and documented in the spec's coverage notes.
- New bundled cross-deployment deterministic spec
  `no-credential-store-write.md`. Forbids shell writes into the host
  credential store: `~/.aws/credentials`, `~/.aws/config`,
  `~/.ssh/id_*`, `~/.ssh/authorized_keys`, `~/.npmrc`, `~/.pypirc`,
  `~/.netrc`, `~/.docker/config.json`, `~/.kube/config`,
  `~/.gnupg/*`, `~/.config/gcloud/*`, `~/.config/op/*`. Covers
  redirection (`>` / `>>`), `tee`, `cp` / `mv` / `install` / `ln`
  with credential path as the last positional arg, and
  `chmod` / `chown` against credential paths. Read-direction
  operations (`cat ~/.aws/credentials`,
  `cp ~/.aws/credentials /tmp/leak`) are out of scope — they belong
  to `no-secret-leak`'s `no-secret-in-output` rule on the resulting
  tool_result. 18 unit tests at
  `tests/test_specs_credential_store.py`, including explicit
  regression locks on read-direction `cp` / `mv`. Severity is
  CRITICAL (no consent override): an agent should compose the
  command and ask the user to run it.
- New bundled cross-deployment deterministic spec
  `no-pkg-install-without-confirm.md`. Gates package-manager install
  commands (`pip install <name>`, `npm install <name>`, `yarn add`,
  `pnpm add`, `cargo install`, `gem install`, `brew install`, `apt
  install`, `apt-get install`, `go install` / `go get`, `uv pip
  install`, `uv add`, `poetry add`, `conda install`) behind the same
  `require_consent` model `destructive-shell-needs-consent` uses.
  Manifest-driven installs (`npm install` with no args, `pip install
  -r requirements.txt`, `pip install -e .`) and non-install package-
  manager subcommands (`pip list`, `apt update`) do not trigger.
  14 unit tests at `tests/test_specs_pkg_install.py`, dogfooded via
  `--bundled-specs cli-safe` against the existing `examples/good-
  transcript.jsonl` (no false-positive) and `examples/bad-transcript.
  jsonl` (no new noise — bad transcript contains no install verbs).

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
- CLI now has `agentaudit list-adapters`, making the installed
  transcript adapter surface discoverable without reading the source.
- `agentaudit check` now fails cleanly on judge-backed specs with a
  targeted error message explaining that `type = judge` rules require
  the Python API (`check(..., judge=...)`), instead of surfacing a raw
  exception path.
- CLI adapter auto-detection now sniffs JSON/JSONL content before
  falling back to filename hints, which avoids false positives such as
  generic `messages-log.json` files being misclassified as Anthropic
  transcripts just because of the filename.
- CLI now has `agentaudit list-specs`, making the bundled spec library
  discoverable from the command line alongside `list-rules` and
  `list-adapters`.
- `agentaudit list-specs --cli-safe` now filters that bundled library
  down to specs that run directly in the CLI, and
  `agentaudit list-specs --verbose` labels each bundled spec as
  deterministic or judge-backed.
- `agentaudit check --bundled-specs cli-safe` now runs the bundled
  deterministic spec set directly from the CLI, while
  `--bundled-specs all` includes judge-backed specs and therefore
  preserves the existing Python-API boundary for those rules.
- `agentaudit check` now de-duplicates overlapping explicit `--spec`
  entries against `--bundled-specs`, so combining the shortcuts does not
  double-run the same bundled rule file.
- GitHub Actions dogfood now exercises `agentaudit check --bundled-specs
  cli-safe` directly on the clean generic, OpenAI Agents, and Anthropic
  worked fixtures instead of spelling out those deterministic spec lists
  by hand.
- `agentaudit list-specs --verbose` now distinguishes
  deployment-specific deterministic specs (currently the explicit
  tool-allowlist bundle) from the broader cross-deployment deterministic
  set, and `--bundled-specs cli-safe` excludes those deployment-specific
  specs so generic clean transcripts do not fail on unrelated allowlist
  policy.
- `agentaudit list-specs --deployment-specific` now exposes just that
  deployment-specific bundled subset, and
  `agentaudit check --bundled-specs deterministic` runs the full
  deterministic library (cross-deployment plus deployment-specific)
  without also pulling in judge-backed rules.
- `agentaudit check --bundled-specs deployment-specific` now runs just
  the deployment-specific deterministic subset, giving CLI users a
  direct execution counterpart to `list-specs --deployment-specific`.
- `agentaudit check --spec ...` now resolves bundled-spec relative paths
  such as `no-secret-leak.md` or
  `openai-agents/tool-allowlist.md` when the bundled spec library is
  present locally, so common examples no longer need full
  `specs/...` filesystem paths.

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
