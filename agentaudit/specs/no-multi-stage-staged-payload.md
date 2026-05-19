# Spec: no multi-stage staged payload execution without consent

The direct dangerous-content rules in
`no-direct-dangerous-shell-content.md` catch single-event payloads:
the file-write content itself contains `curl | sh`, a base64-decode
pipe, or another immediately dangerous shell pattern.

This spec closes the next evasive step: an agent writes a dominantly
encoded blob to disk in one event, then later decodes that same file
into an interpreter in a separate event. Neither event is sufficient
on its own for the earlier single-event rules, but the two-event chain
is still the same underlying harm.

Severity stays HIGH `require_consent` because legitimate analogues
exist in test fixtures, release artifacts, or intentionally staged
debug flows. The user just has to approve the pattern explicitly.

## staged-payload-needs-consent: gate same-session encoded-blob writes that later execute through the shell

```agentaudit
type = staged_payload
severity = high
ignore_case = true
seed_tools = ["Edit", "Write", "MultiEdit", "NotebookEdit", "str_replace_editor", "create_file", "write_file", "file_write", "mcp__filesystem__write_file", "mcp__filesystem__create_file", "mcp__filesystem__edit_file"]
seed_args = ["content", "new_string", "edits"]
seed_path_args = ["file_path", "path", "notebook_path", "uri"]
seed_content_patterns = ["(?ms)\\A\\s*[A-Za-z0-9+/=\\s]{256,}\\s*\\Z", "(?ms)\\A\\s*(?:[0-9a-fA-F]{2}\\s*){128,}\\s*\\Z"]
consume_tools = ["Bash", "execute_command", "shell", "run_command"]
consume_args = ["command"]
consume_command_patterns = ["(?:(?:base64\\s+(?:-d|--decode|-D)|xxd\\s+-r(?:\\s+-p)?|gunzip|gzip\\s+-d|zcat)\\s+(?:<\\s*)?[\\'\"]?<SEED_PATH>[\\'\"]?\\s*(?:\\|\\s*(?:sh|bash|zsh|python|python3|node|ruby|perl)\\b)|(?:sh|bash|zsh|source|\\.)\\s+[\\'\"]?<SEED_PATH>[\\'\"]?\\b)"]
same_actor_only = true
consent_phrases = ["yes, the encoded blob is intentional", "yes, write the staged script", "i approve the multi-stage install"]
```

The seed side is intentionally tight:

- the file-write content must be dominantly an encoded blob, not just
  contain a small base64 field inside JSON or Markdown
- the consume side must reference the same path written earlier
- same-actor only for this first lane, to keep tool-result and
  notebook-output false positives out of the bundled default

Coverage notes:

- Quoted consume paths are allowed: `'path'` and `"path"` both count.
- Redirection forms are allowed: `base64 -d < payload.b64 | sh`.
- Out of scope for this first lane: cross-actor staged payloads,
  obfuscated path construction, and rare encoding families.
