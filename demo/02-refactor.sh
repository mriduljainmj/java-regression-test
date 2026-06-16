#!/usr/bin/env bash
# DEMO B — a change that should NOT generate tests.
# Pure internal refactor: renames a private constant in OrderService. No
# endpoint, status code, payload, or message changes. The agent should analyze
# the diff and return "purely internal — no tests needed", showing it reasons
# about behavior rather than blindly generating.
set -euo pipefail
cd "$(dirname "$0")/.."

FILE="java-component/src/main/java/com/example/products/OrderService.java"

python3 - <<PY
from pathlib import Path
p = Path("$FILE")
s = p.read_text()
assert "MAX_ORDER_TOTAL" in s, "DEMO B already applied — run demo/reset.sh first"
# Rename the constant everywhere it appears — behavior is byte-for-byte identical.
s = s.replace("MAX_ORDER_TOTAL", "ORDER_TOTAL_CAP")
p.write_text(s)
print("✓ Renamed MAX_ORDER_TOTAL -> ORDER_TOTAL_CAP in OrderService.java (no behavior change)")
PY

git add "$FILE"   # commit ONLY this file, never -A
git commit -q -m "refactor: rename order-total cap constant"
echo
echo "✅ Committed. When you're ready to demo, run:  git push"
echo "   → 'generate-tests' fires but the agent should produce NO PR (internal change)."
echo "   → Show the workflow log line: 'purely internal ... no tests'."
