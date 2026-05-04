#!/usr/bin/env bash
# watch.sh — monitor the comms folder for new messages from the other agent.
#
# Usage:
#   ./comms/watch.sh                # follow all boards
#   ./comms/watch.sh claude         # show only updates to claude-board.md
#   ./comms/watch.sh codex          # show only updates to codex-board.md
#   ./comms/watch.sh once           # print a single diff snapshot and exit
#
# Strategy: hash each tracked file, compare every INTERVAL seconds, print a
# unified diff when any file changes. Works without inotify so it's portable.

set -euo pipefail

INTERVAL="${WATCH_INTERVAL:-3}"
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

TARGETS=(claude-board.md codex-board.md shared-decisions.md ideas.md)
case "${1:-all}" in
  claude)  TARGETS=(claude-board.md) ;;
  codex)   TARGETS=(codex-board.md) ;;
  shared)  TARGETS=(shared-decisions.md) ;;
  ideas)   TARGETS=(ideas.md) ;;
  once)    ONCE=1 ;;
  all|"")  ;;
  *)       echo "unknown filter: $1" >&2; exit 2 ;;
esac

snap_dir="$(mktemp -d)"
trap 'rm -rf "$snap_dir"' EXIT

snapshot() {
  for f in "${TARGETS[@]}"; do
    [[ -f "$f" ]] && cp "$f" "$snap_dir/$f.prev" || true
  done
}

diffshot() {
  local changed=0
  for f in "${TARGETS[@]}"; do
    [[ -f "$f" ]] || continue
    if ! cmp -s "$f" "$snap_dir/$f.prev" 2>/dev/null; then
      echo
      echo "=== $(date -u +%FT%TZ)  $f changed ==="
      diff -u "$snap_dir/$f.prev" "$f" 2>/dev/null || cat "$f"
      cp "$f" "$snap_dir/$f.prev"
      changed=1
    fi
  done
  return $((1 - changed))
}

snapshot
echo "watching: ${TARGETS[*]}  (interval ${INTERVAL}s, Ctrl-C to stop)"

if [[ "${ONCE:-0}" == "1" ]]; then
  diffshot || echo "no changes."
  exit 0
fi

while true; do
  diffshot || true
  sleep "$INTERVAL"
done
