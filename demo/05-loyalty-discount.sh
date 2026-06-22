#!/usr/bin/env bash
# DEMO E — designed to make the GENERATED test fail first, then self-correct.
# Adds a loyalty discount that stacks MULTIPLICATIVELY on top of the bulk
# discount. Models almost always compute stacked discounts ADDITIVELY first, so
# the agent's first-pass expected total is usually wrong → `mvn test` fails →
# the run_generated_tests loop feeds the failure back → the model corrects the
# arithmetic and regenerates. This is the change to push when you want to SHOW
# the retry loop working.
#
#   50 units @ 100.00, loyalty member:
#     bulk (50+ units) = 10%  ->  100*50*0.90 = 4500.00
#     loyalty stacks   = 10%  ->  4500.00 * 0.90 = 4050.00   (CORRECT)
#     naive additive (20% off) would be 4000.00              (the wrong guess)
#
# Existing scenarios are unaffected: loyaltyMember defaults to false.
set -euo pipefail
cd "$(dirname "$0")/.."

REQ="java-component/src/main/java/com/example/products/OrderRequest.java"
SVC="java-component/src/main/java/com/example/products/OrderService.java"

python3 - <<PY
from pathlib import Path

req = Path("$REQ"); r = req.read_text()
assert "loyaltyMember" not in r, "DEMO E already applied — run demo/reset.sh first"
r = r.replace(
    "    private Integer quantity;\n",
    "    private Integer quantity;\n\n    private boolean loyaltyMember;\n",
    1,
)
r = r.replace(
    "    public void setQuantity(Integer quantity) {\n"
    "        this.quantity = quantity;\n"
    "    }\n",
    "    public void setQuantity(Integer quantity) {\n"
    "        this.quantity = quantity;\n"
    "    }\n\n"
    "    public boolean isLoyaltyMember() {\n"
    "        return loyaltyMember;\n"
    "    }\n\n"
    "    public void setLoyaltyMember(boolean loyaltyMember) {\n"
    "        this.loyaltyMember = loyaltyMember;\n"
    "    }\n",
)
req.write_text(r)
print("✓ OrderRequest.loyaltyMember added")

svc = Path("$SVC"); s = svc.read_text()
s = s.replace(
    "    private static final double SMALL_TIER_DISCOUNT = 0.05;\n",
    "    private static final double SMALL_TIER_DISCOUNT = 0.05;\n"
    "    // Loyalty members get an extra 10% that STACKS multiplicatively.\n"
    "    private static final double LOYALTY_DISCOUNT = 0.10;\n",
)
s = s.replace(
    "        double total = round2(product.getPrice() * quantity * (1 - discount));\n"
    "        if (total > MAX_ORDER_TOTAL) {\n",
    "        double total = round2(product.getPrice() * quantity * (1 - discount));\n"
    "        if (request.isLoyaltyMember()) {\n"
    "            total = round2(total * (1 - LOYALTY_DISCOUNT));\n"
    "        }\n"
    "        if (total > MAX_ORDER_TOTAL) {\n",
)
svc.write_text(s)
print("✓ OrderService applies loyalty discount multiplicatively")
PY

git add "$REQ" "$SVC"   # commit ONLY these two files, never -A
git commit -q -m "feat: stacking loyalty discount on orders"
echo
echo "✅ Committed. When you're ready to demo, run:  git push"
echo "   → 'generate-tests' runs; the agent likely asserts 4000.00 (additive),"
echo "     'mvn test' fails (actual 4050.00), and the loop self-corrects."
echo "   → Watch the workflow log for: 'Test attempt 1 failed ... Test attempt 2'."
