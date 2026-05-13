#!/usr/bin/env bash
# agentaudit / claude-code-user-prompt-submit.sh
#
# Companion to `claude-code-pre-tool-use.sh`. Wire this at
# .claude/hooks/user-prompt-submit.sh in a Claude Code project so
# every user prompt is recorded into the same history file the
# PreToolUse hook reads. This is the missing second ingestion path
# that makes consent-gated specs (pkg-install, runtime-config,
# instruction-file, destructive-shell) actually clear when the user
# says "yes, install it" / "yes, edit it" / "go ahead" in chat.
#
# Without this hook, the bare PreToolUse recipe only ever sees
# tool-call events, so require_consent rules fail closed by design —
# even after the user has explicitly approved the operation in chat.
#
# Quick install:
#   mkdir -p .claude/hooks
#   cp recipes/claude-code-user-prompt-submit.sh .claude/hooks/user-prompt-submit.sh
#   chmod +x .claude/hooks/user-prompt-submit.sh
#
# Register in .claude/settings.json alongside the PreToolUse hook:
#   {
#     "hooks": {
#       "PreToolUse": [...],
#       "UserPromptSubmit": [
#         {
#           "hooks": [
#             { "type": "command", "command": ".claude/hooks/user-prompt-submit.sh" }
#           ]
#         }
#       ]
#     }
#   }
#
# The history file path MUST match the one your PreToolUse hook uses
# (default ${CLAUDE_PROJECT_DIR}/.claude/agentaudit-history.jsonl).

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
HIST="${AGENTAUDIT_HISTORY:-${PROJECT_DIR}/.claude/agentaudit-history.jsonl}"

mkdir -p "$(dirname "${HIST}")"

# Claude Code's UserPromptSubmit hook hands the prompt to the script
# on stdin. agentaudit ingest accepts either the bare prompt text or
# a wrapper JSON shape with a `prompt` / `text` / `content` field, so
# this works regardless of which envelope Claude Code's runtime
# happens to use for this hook event.
exec agentaudit ingest \
    --history-file "${HIST}" \
    --actor user \
    --event-kind message
