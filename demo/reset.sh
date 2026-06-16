#!/usr/bin/env bash
# Undo the most recent demo commit, IF it was one of the demo scripts and has
# not been pushed yet. Safe: refuses to touch pushed history or non-demo commits,
# and only ever resets a single demo commit (the demo kit itself is committed
# separately, so it is never at risk).
set -euo pipefail
cd "$(dirname "$0")/.."

msg=$(git log -1 --pretty=%s)
case "$msg" in
  "feat: cap product price at 100000.00"|\
  "refactor: rename order-total cap constant"|\
  "demo: change product-not-found message (breaks existing assertion)")
    ;;
  *)
    echo "Last commit isn't a demo commit ($msg) — nothing to reset."; exit 0;;
esac

# Guard: don't rewrite already-pushed history.
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "")
if [ -n "$upstream" ] && git merge-base --is-ancestor HEAD "$upstream" 2>/dev/null; then
  echo "This commit is already pushed to $upstream."
  echo "Reverting on the remote rewrites history — do that manually if you really mean to."
  exit 1
fi

# A demo commit touches exactly one source file (scoped add), so a soft reset +
# checkout restores it without endangering anything else in the tree.
git reset --soft HEAD~1
git restore --staged --worktree -- "java-component/" 2>/dev/null || git checkout -- "java-component/"
echo "✓ Reverted: $msg"
