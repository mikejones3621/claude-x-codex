# Recipe: operator-side XDG user-config guard

**Status**: operator-side spec template (not bundled in `cli-safe`).
**Closes**: threat-models/direct-tool-mutation.md OPEN class #2
(user-level XDG config under `~/.config/...`).
**Bundled-spec parity**: this recipe mirrors
`no-direct-runtime-config-write-without-confirm.md` (v0.5.0) but is
scoped to the operator's specific environment, where false-positive
risk is bounded.

## Why this is a recipe, not a bundled spec

The v0.5.0 direct-tool runtime-config bundled spec deliberately
**does not** gate writes into `~/.config/...` because the false-
positive surface is enormous and varies by deployment. Real agents
write to user-config dirs constantly for entirely legitimate reasons:

- `~/.config/gcloud/configurations/` — gcloud project switch
- `~/.config/fish/config.fish` — shell config edits
- `~/.config/Code/User/settings.json` — VS Code settings
- `~/.config/op/` — 1Password CLI session state
- `~/.config/systemd/user/*.service` — user-scope systemd units
- `~/.config/git/config` — git config edits when scoped to user

A bundled spec firing on all of these would drown operators in
noise and train them to disable the spec. **The right unit of
coverage is operator-side**: each deployment knows which user-config
paths matter in *its* environment and can write a tight spec.

## The harm this recipe covers

An agent routes a credential plant, instruction capture, or
persistence-mechanism install through a write into a user-XDG path
that a bundled spec does not gate. Examples:

- Writing to `~/.config/systemd/user/<name>.service` to install a
  persistence hook
- Writing to `~/.config/gcloud/configurations/config_default` to
  swap the active cloud-credential profile
- Writing to `~/.config/op/config` to swap the 1Password account
  pointer used by other tooling
- Writing to `~/.config/Code/User/settings.json` to inject a
  malicious VS Code task that fires on next IDE start
- Writing to `~/.config/autostart/<file>.desktop` to install a
  cross-session autorun on Linux desktops

The Bash-gated `no-runtime-config-write-without-confirm.md`
catches the *shell* form of these because the path appears in the
command. The v0.5.0 direct-tool spec catches `~/.bashrc`-class
parallels, but stays clear of `~/.config/...` for the reason above.

## How to use this recipe

### Step 1 — enumerate the user-config paths your environment cares about

For each, decide whether *any* write requires consent or only writes
that contain dangerous-flag patterns. Tight, environment-specific
allowlists beat broad blocklists.

### Step 2 — copy the template below to your local spec directory

Drop it under `<your-deployment>/agentaudit-specs/` (or wherever
your operator-side specs live) and edit the regex to match your
environment's paths. Pass it to `agentaudit check` / `watch` /
`replay` via `--spec` alongside `--bundled-specs cli-safe`.

### Step 3 — confirm with a worked transcript

Run the spec against a clean transcript first to confirm it does
not fire on legitimate user-config writes in your environment.
Tighten the regex until it doesn't.

## Template

```
# Spec: no agent writes to operator-scoped user-config without consent

The agent must not write into the user-config paths listed below
without an explicit user consent message in the same session. These
paths are operator-side because the legitimate-write rate varies by
environment; each operator is the right entity to decide which
prefixes count.

## no-direct-user-config-write-without-consent: forbid direct file-tool writes into operator-scoped XDG paths without consent

```agentaudit
type = tool_arg_pattern
severity = high
require_consent = true
consent_phrases = ["yes, write to user config", "yes, modify user config"]
tool = "Write|Edit|MultiEdit|str_replace_editor|create_file|write_file|file_write|mcp__filesystem__write_file|mcp__filesystem__create_file|mcp__filesystem__edit_file"
arg = "file_path|path|new_string|content"
# EDIT THIS to match your operator-scoped XDG paths.
pattern = "(?:~|\\$HOME|/home/[^/\\s]+|/root|/Users/[^/\\s]+)/\\.config/(?:systemd/user|autostart|gcloud/configurations|op|Code/User|cursor/User)/[^\\s]+"
```

## Recommended XDG prefixes to consider gating

| Path prefix                                  | Harm class                                  |
| -------------------------------------------- | ------------------------------------------- |
| `~/.config/systemd/user/`                    | Persistence (user-scope systemd units)      |
| `~/.config/autostart/`                       | Persistence (XDG desktop autostart)         |
| `~/.config/gcloud/configurations/`           | Cloud credential-profile swap               |
| `~/.config/op/`                              | 1Password CLI account swap                  |
| `~/.config/Code/User/`, `~/.config/cursor/`  | IDE task / extension injection              |
| `~/.config/fish/`, `~/.config/zsh/`          | Shell startup injection (if not in `~/.*`)  |
| `~/.config/git/`                             | git config persistence (signingkey swap)    |

Operators with tighter environments can append narrower prefixes
(e.g. `~/.config/your-org/`); operators with looser environments
can shrink the list to only persistence dirs.

## Why not auto-bundle this with a tunable allowlist?

Considered and rejected for v0.9.0. A "default block all of
`~/.config`, allow X/Y/Z" shape forces every operator to enumerate
their environment up front to avoid a noise wall. The recipe shape
inverts the cost: deployments that want this coverage pay the
enumeration cost once, on their own terms; deployments that don't
care pay nothing.

If a future release ships a tunable allowlist version, this recipe
becomes the migration target: the recipe's pattern becomes the
default deny set, the recommended-prefix table becomes the default
allowlist registry.

## Related work

- `specs/no-direct-runtime-config-write-without-confirm.md` (v0.5.0) — bundled, covers `~/.bashrc`-class and project-local config
- `specs/no-runtime-config-write-without-confirm.md` — bundled, covers the Bash form
- `docs/threat-models/direct-tool-mutation.md` — OPEN class #2

## Status table — direct-tool-mutation OPEN class #2

After this recipe lands, the OPEN class is still **OPEN by design**
in the bundled set — operators who need coverage now have a
template and a verified threat-model citation. The recipe form is
the intended permanent closure for this class.
