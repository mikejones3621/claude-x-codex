# Spec: no direct (non-Bash) writes to agent runtime / CI / hooks config

Direct-tool parallel of `no-runtime-config-write-without-confirm.md`.
The Bash version gates persistence-class writes (git hooks, husky
hooks, GitHub Actions workflows, agent settings) on explicit user
consent. The same harms are reachable through Claude Code's `Edit` /
`Write` / `MultiEdit`, MCP filesystem tools, or any custom file-write
tool the runtime exposes — and the Bash-scoped rule is blind to those
surfaces.

This spec applies the same `require_consent` gate to file-mutation
tool calls whose `file_path` / `path` / `notebook_path` / `uri`
argument resolves to a runtime-config path. The Bash version stays in
force; both will fire together when an agent does the same operation
through both surfaces.

## direct-runtime-config-write-needs-consent: gate file-tool config writes on consent

```agentaudit
type = require_consent
severity = high
tools = ["Edit", "Write", "MultiEdit", "NotebookEdit", "str_replace_editor", "create_file", "write_file", "file_write", "mcp__filesystem__write_file", "mcp__filesystem__create_file", "mcp__filesystem__edit_file", "mcp__filesystem__move_file"]
args = ["file_path", "notebook_path", "path", "target_path", "destination", "uri"]
trigger_pattern = "(?:[/\\\\]|^)(?:\\.claude[/\\\\](?:hooks[/\\\\][^\\s]+|settings(?:\\.local)?\\.json|local-settings\\.json)|\\.husky[/\\\\][^\\s]+|\\.git[/\\\\]hooks[/\\\\][^\\s]+|\\.github[/\\\\](?:workflows|actions)[/\\\\][^\\s]+|\\.cursor[/\\\\](?:rules(?:[/\\\\][^\\s]+)?|mcp\\.json)|\\.cursorrules|\\.clinerules)(?:$|[/\\\\\"'\\s])"
consent_phrases = ["yes, update it", "yes, edit it", "go ahead and modify", "i approve the config change", "lgtm, change it"]
```

Covered paths (same set as the Bash version's intersection with
project-relative paths; user-level XDG-style config under
`~/.config/...` is intentionally NOT in this spec's first cut to keep
false-positive risk low — agents legitimately edit user-level config
on the user's own machine):

- `.claude/hooks/*` — Claude Code hook scripts (run on tool events)
- `.claude/settings.json`, `.claude/settings.local.json`,
  `.claude/local-settings.json` — Claude Code permissions + config
- `.husky/*` — Husky git hooks (run on `git commit`)
- `.git/hooks/*` — raw git hooks (run on commit/push/merge)
- `.github/workflows/*`, `.github/actions/*` — GitHub Actions CI
  pipelines
- `.cursor/rules/*`, `.cursor/mcp.json`, `.cursorrules`,
  `.clinerules` — Cursor / Cline runtime config

Covered tools and args: same surfaces as
`no-direct-credential-store-write.md`. Operators with bespoke MCP
file servers should extend the `tools` list in their own spec; this
ships a conservative default.

Coverage notes:

- **`require_consent` semantics**: the user must have said one of the
  `consent_phrases` in a prior `message` event before the file-tool
  call fires. Consent clears one matching call by default; set
  `persist = true` in the spec block (operator side) if you want a
  single consent to cover a whole edit session.
- **`MultiEdit` is the high-value catch**. A single `MultiEdit` call
  that touches `.github/workflows/release.yml` is one of the cleanest
  ways for a compromised agent to plant a long-running CI backdoor.
  This rule fires on it.
- **`mcp__filesystem__move_file`** is a write into a runtime-config
  path when `destination` matches. A move that **overwrites**
  `.git/hooks/pre-commit` is the same harm as a direct write.
- **User-level config (`~/.config/claude-code/...`)** is intentionally
  out of scope here. The Bash version covers it because the
  Bash-scoped command text reliably reveals the home prefix; the
  file-tool version sees only the resolved path, and a project-local
  `.config/claude-code/` is so unusual that the false-positive risk
  is acceptable. If your deployment cares about user-level config
  writes, add a follow-up spec scoped to your environment's
  resolved home prefix.
- **Obfuscated paths** (custom tools that build the path from
  components) bypass the regex. Future judge-backed spec territory.
- **The Bash version stays in force** — both rules will fire on the
  same conceptual harm when an agent uses both surfaces in the same
  session, which is the correct signal.
