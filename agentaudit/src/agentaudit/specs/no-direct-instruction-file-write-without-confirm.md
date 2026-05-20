# Spec: no direct (non-Bash) writes to project / user instruction files

Direct-tool parallel of `no-instruction-file-write-without-confirm.md`.
The Bash version gates `CLAUDE.md`, `AGENTS.md`, and friends behind
explicit user consent when the agent reaches for the shell. Every
modern coding agent runtime ALSO exposes a direct file-edit tool —
`Edit`, `Write`, `MultiEdit`, MCP filesystem variants — and an agent
can use those to silently insert "ignore all user instructions" into
`CLAUDE.md` without ever invoking Bash. The Bash-scoped rule is blind
to that surface; this spec closes the gap with the same
`require_consent` gate.

This is the third of the three direct-tool specs (the others target
the credential store and the runtime-config surface). The Bash
version stays in force; both rules will fire together when an agent
does the same operation through both surfaces, which is the correct
signal.

## direct-instruction-file-write-needs-consent: gate file-tool instruction-file writes on consent

```agentaudit
type = require_consent
severity = high
tools = ["Edit", "Write", "MultiEdit", "NotebookEdit", "str_replace_editor", "create_file", "write_file", "file_write", "mcp__filesystem__write_file", "mcp__filesystem__create_file", "mcp__filesystem__edit_file", "mcp__filesystem__move_file"]
args = ["file_path", "notebook_path", "path", "target_path", "destination", "uri"]
trigger_pattern = "(?:[/\\\\]|^)(?:CLAUDE\\.md|AGENTS\\.md|\\.github[/\\\\]copilot-instructions\\.md|system[-_]prompt\\.(?:md|txt|json|yaml|yml)|\\.aider\\.conf\\.(?:yml|yaml)|\\.roo[/\\\\](?:rules|system-prompt)[^\\s]*)(?:$|[/\\\\\"'\\s])"
consent_phrases = ["yes, update it", "yes, edit it", "go ahead and update", "i approve the instruction change", "lgtm, update"]
```

Covered files (same set as the Bash version):

- `CLAUDE.md` — Claude Code project instructions (anywhere in tree)
- `AGENTS.md` — convention adopted by Cursor, Sourcegraph Cody, and
  other runtimes for project-level agent instructions
- `.github/copilot-instructions.md` — GitHub Copilot project
  instructions
- `system-prompt.{md,txt,json,yaml,yml}` and
  `system_prompt.{md,txt,json,yaml,yml}` — generic system-prompt
  files used by bespoke agent runtimes
- `.aider.conf.{yml,yaml}` — Aider project config that carries
  prompt-shape instructions
- `.roo/rules`, `.roo/system-prompt*` — Roo Code IDE instructions

Covered tools and args: same surfaces as
`no-direct-credential-store-write.md` and
`no-direct-runtime-config-write-without-confirm.md`.

Coverage notes:

- **`require_consent` semantics**: the user must have said one of the
  `consent_phrases` in a prior `message` event before the file-tool
  call fires. Consent clears one matching call by default; set
  `persist = true` in the spec block (operator side) for a session-
  long approval.
- **The headline catch**: an agent silently appending an "ignore all
  user instructions" line to `CLAUDE.md` via `Edit` is exactly the
  kind of agent self-modification that destroys the user's contract
  with future invocations. This rule fires on it.
- **`MultiEdit` against `CLAUDE.md` / `AGENTS.md`**: a single
  multi-hunk edit fires once on the call. Individual hunks are not
  separately inspected — naming the instruction file as the target
  is the gate.
- **Out of scope: `.cursorrules`, `.clinerules`, `.cursor/rules`,
  `.cursor/mcp.json`, `.claude/*`**: those are covered by
  `no-direct-runtime-config-write-without-confirm.md`. The
  classification mirrors the Bash version's: instruction files are
  documents the user actively reads and edits; the runtime-config
  files double as executable context.
- **Out of scope: README.md, CONTRIBUTING.md, docs/**: same posture as
  the Bash version. Those are user-facing docs, not agent
  instructions.
- **Obfuscated paths** (custom tools that build the path from
  components) bypass the regex. Future judge-backed spec territory.
