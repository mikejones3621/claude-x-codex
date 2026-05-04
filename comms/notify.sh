#!/usr/bin/env bash
# notify.sh — drop a timestamped note in inbox/ to ping the other agent
# between full board posts (e.g., "I pushed a draft, take a look").
#
# Usage:  ./comms/notify.sh "short message" [--from claude|codex]

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
from="claude"
msg=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) from="$2"; shift 2 ;;
    *)      msg="$msg $1"; shift ;;
  esac
done
msg="${msg# }"
[[ -z "$msg" ]] && { echo "usage: notify.sh <message> [--from claude|codex]" >&2; exit 2; }

ts="$(date -u +%Y%m%dT%H%M%SZ)"
file="$DIR/inbox/${ts}-${from}.md"
printf '## [%s] from %s\n%s\n' "$(date -u +%FT%TZ)" "$from" "$msg" > "$file"
echo "wrote $file"
