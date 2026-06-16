#!/usr/bin/env bash
# DEMO D — the safety-net moment (zero LLM involvement, 100% deterministic).
# Changes an error message the existing suite asserts on. The regression run
# goes RED and the dashboard's right pane shows the exact failing scenario —
# proving code/test drift is caught, not silently shipped.
set -euo pipefail
cd "$(dirname "$0")/.."

FILE="java-component/src/main/java/com/example/products/ProductNotFoundException.java"

python3 - <<PY
from pathlib import Path
p = Path("$FILE")
s = p.read_text()
assert "Product not found with id" in s, "DEMO D already applied — run demo/reset.sh first"
s = s.replace("Product not found with id: ", "No product exists with id: ")
p.write_text(s)
print("✓ Changed the not-found message; the suite still asserts the old text.")
PY

git add "$FILE"   # commit ONLY this file, never -A
git commit -q -m "demo: change product-not-found message (breaks existing assertion)"
echo
echo "✅ Committed. When you're ready to demo, run:  git push"
echo "   → 'regression' goes RED. Open the dashboard: the failing scenario lights up."
echo "   → Talking point: code and tests drifted; the gate caught it before release."
