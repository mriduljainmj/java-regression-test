#!/usr/bin/env bash
# DEMO A — a change that SHOULD generate tests.
# Adds a maximum-price cap to product creation/update: a new 400 unhappy path
# on existing endpoints. Existing scenarios (small prices) still pass, so the
# agent's job is to ADD a boundary scenario for the new rule.
set -euo pipefail
cd "$(dirname "$0")/.."

FILE="java-component/src/main/java/com/example/products/ProductRequest.java"

python3 - <<PY
from pathlib import Path
p = Path("$FILE")
s = p.read_text()
assert '@DecimalMax' not in s, "DEMO A already applied — run demo/reset.sh first"
s = s.replace(
    "import jakarta.validation.constraints.NotNull;",
    "import jakarta.validation.constraints.DecimalMax;\n"
    "import jakarta.validation.constraints.NotNull;",
)
s = s.replace(
    '    @NotNull(message = "price is required")\n'
    '    @Positive(message = "price must be greater than zero")\n',
    '    @NotNull(message = "price is required")\n'
    '    @Positive(message = "price must be greater than zero")\n'
    '    @DecimalMax(value = "100000.00", message = "price must not exceed 100000.00")\n',
)
p.write_text(s)
print("✓ Added @DecimalMax price cap to ProductRequest.java")
PY

git add "$FILE"   # commit ONLY this file, never -A
git commit -q -m "feat: cap product price at 100000.00"
echo
echo "✅ Committed. When you're ready to demo, run:  git push"
echo "   → 'generate-tests' fires; expect a PR adding a price-cap boundary scenario."
