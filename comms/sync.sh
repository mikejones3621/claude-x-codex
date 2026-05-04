#!/usr/bin/env bash
# sync.sh — safely commit + push to trunk in trunk-based mode.
#
# Both agents (Claude and Codex) should use this between every chunk of
# work, instead of `git push` directly. It:
#   1. verifies the git remote is the operator's repo,
#   2. rebases the current branch on origin/main,
#   3. runs tests for any subproject you touched (currently agentaudit/),
#   4. pushes to origin/main only if tests pass,
#   5. retries push with exponential backoff on transient network errors.
#
# Usage:
#   comms/sync.sh                 # rebase, test, push (assumes you've committed)
#   comms/sync.sh --commit "msg"  # stage all changes, commit "msg", then sync
#   comms/sync.sh --no-test       # skip tests (use sparingly — only for
#                                  # docs-only or comms/ changes)
#   comms/sync.sh --dry-run       # do everything except the actual push
#
# Environment:
#   AGENT=claude|codex   sets the signature appended to commit messages.

set -euo pipefail

EXPECTED_REMOTE_FRAGMENT="mikejones3621/claude-x-codex"
BRANCH="main"
DO_COMMIT=""
DO_TEST=1
DRY_RUN=0
AGENT="${AGENT:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit)   DO_COMMIT="${2:-}"; shift 2 ;;
    --no-test)  DO_TEST=0; shift ;;
    --dry-run)  DRY_RUN=1; shift ;;
    --agent)    AGENT="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "sync.sh: unknown flag: $1" >&2
      exit 2
      ;;
  esac
done

repo_root() {
  git rev-parse --show-toplevel
}

ROOT="$(repo_root)"
cd "$ROOT"

# 1. Verify remote.
if ! git remote -v | grep -qF "$EXPECTED_REMOTE_FRAGMENT"; then
  echo "sync.sh: refusing to push — no remote points at $EXPECTED_REMOTE_FRAGMENT." >&2
  echo "         Ask the operator to wire 'origin' to the canonical repo." >&2
  echo "         Current remotes:" >&2
  git remote -v | sed 's/^/             /' >&2
  exit 3
fi

# 2. Make sure we're on main.
current="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current" != "$BRANCH" ]]; then
  echo "sync.sh: refusing to push from branch '$current' (expected '$BRANCH')." >&2
  echo "         Trunk-based mode: commit directly to main." >&2
  exit 4
fi

# 3. Optional: stage and commit current changes.
if [[ -n "$DO_COMMIT" ]]; then
  git add -A
  if git diff --cached --quiet; then
    echo "sync.sh: --commit given but nothing is staged; skipping commit."
  else
    sig=""
    case "$AGENT" in
      claude) sig="(claude)" ;;
      codex)  sig="(codex)"  ;;
      "")     ;;  # no signature; recommended to set $AGENT
      *)      sig="($AGENT)" ;;
    esac
    if [[ -n "$sig" ]]; then
      git commit -m "$DO_COMMIT" -m "$sig"
    else
      git commit -m "$DO_COMMIT"
      echo "sync.sh: warning — no AGENT signature; set AGENT=claude or AGENT=codex." >&2
    fi
  fi
fi

# 4. Bail out if there are uncommitted changes — we don't want to rebase over them.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "sync.sh: uncommitted changes present; commit them first (or use --commit)." >&2
  git status --short >&2
  exit 5
fi

# 5. Fetch and rebase on origin/main.
echo "sync.sh: fetching origin/$BRANCH..."
git fetch origin "$BRANCH"
echo "sync.sh: rebasing local $BRANCH onto origin/$BRANCH..."
if ! git rebase "origin/$BRANCH"; then
  echo "sync.sh: rebase produced conflicts. Resolve them, then run sync.sh again." >&2
  echo "         To abort and try over: git rebase --abort" >&2
  exit 6
fi

# 6. Run tests for affected subprojects.
if [[ "$DO_TEST" -eq 1 ]]; then
  changed="$(git diff --name-only "origin/$BRANCH"...HEAD || true)"
  if echo "$changed" | grep -q '^agentaudit/'; then
    echo "sync.sh: agentaudit/ changed — running pytest..."
    if ! ( cd agentaudit && python -m pytest -q ); then
      echo "sync.sh: tests FAILED. Refusing to push a broken main." >&2
      exit 7
    fi
  else
    echo "sync.sh: no agentaudit/ changes; skipping pytest."
  fi
else
  echo "sync.sh: --no-test set; skipping tests."
fi

# 7. Push, with retry on transient errors.
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "sync.sh: --dry-run set; not pushing."
  exit 0
fi

attempt=0
delay=2
while true; do
  attempt=$((attempt + 1))
  if git push -u origin "$BRANCH"; then
    echo "sync.sh: pushed."
    exit 0
  fi
  rc=$?
  # Non-fast-forward usually means another agent pushed while we were testing.
  # Re-fetch and rebase, then retry.
  echo "sync.sh: push failed (rc=$rc); fetching + rebasing and retrying..." >&2
  git fetch origin "$BRANCH" || true
  if ! git rebase "origin/$BRANCH"; then
    echo "sync.sh: rebase after failed push produced conflicts; aborting." >&2
    echo "         Resolve manually and re-run sync.sh." >&2
    exit 8
  fi
  if [[ "$attempt" -ge 4 ]]; then
    echo "sync.sh: giving up after $attempt push attempts." >&2
    exit 9
  fi
  sleep "$delay"
  delay=$((delay * 2))
done
