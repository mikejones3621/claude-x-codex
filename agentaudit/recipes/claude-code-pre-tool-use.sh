#!/usr/bin/env bash
# agentaudit / claude-code-pre-tool-use.sh
#
# Drop this script at .claude/hooks/pre-tool-use.sh in a Claude Code
# project to gate every tool call through agentaudit's live blocker.
#
# Quick install:
#   mkdir -p .claude/hooks
#   cp recipes/claude-code-pre-tool-use.sh .claude/hooks/pre-tool-use.sh
#   chmod +x .claude/hooks/pre-tool-use.sh
#
# Then register in .claude/settings.json:
#   {
#     "hooks": {
#       "PreToolUse": [
#         {
#           "matcher": "Bash",
#           "hooks": [
#             { "type": "command", "command": ".claude/hooks/pre-tool-use.sh" }
#           ]
#         }
#       ]
#     }
#   }
#
# Exit code 0 → Claude Code proceeds with the tool call.
# Exit code 1 → Claude Code refuses the call (agentaudit blocked it).
# Exit code 2 → malformed input from the hook system; fail-closed.
#
# Customize the bundled-spec set or block-severity threshold below to
# match your environment. See docs/recipes/claude-code-hook.md for
# tuning guidance and caveats.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
HIST="${AGENTAUDIT_HISTORY:-${PROJECT_DIR}/.claude/agentaudit-history.jsonl}"
LOG="${AGENTAUDIT_LOG:-${PROJECT_DIR}/.claude/agentaudit-violations.jsonl}"
BUNDLED_SET="${AGENTAUDIT_BUNDLED_SET:-cli-safe}"
BLOCK_SEVERITY="${AGENTAUDIT_BLOCK_SEVERITY:-high}"

# Make sure history/log directories exist (agentaudit will create them
# but we'd rather fail loudly here than have agentaudit silently fail
# under permission errors).
mkdir -p "$(dirname "${HIST}")" "$(dirname "${LOG}")"

exec agentaudit watch \
    --mode hook \
    --bundled-specs "${BUNDLED_SET}" \
    --block-severity "${BLOCK_SEVERITY}" \
    --history-file "${HIST}" \
    --log-file "${LOG}"
