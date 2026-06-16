#!/usr/bin/env bash
# DEMO C — the "writes its own test code" finale.
# Adds GET /api/v1/orders (list all orders). No existing step definition can
# express "list all orders", so the agent must propose a new Java STEPDEF block
# (glue using TestContext) AND scenarios that use it. Higher LLM variance than
# A/B/D — rehearse once before relying on it live.
set -euo pipefail
cd "$(dirname "$0")/.."

SVC="java-component/src/main/java/com/example/products/OrderService.java"
CTL="java-component/src/main/java/com/example/products/OrderController.java"

python3 - <<PY
from pathlib import Path

svc = Path("$SVC"); s = svc.read_text()
assert "public java.util.List<Order> findAll()" not in s, "DEMO C already applied — run demo/reset.sh first"
s = s.replace(
    "    public boolean hasOrdersForProduct(Long productId) {",
    "    public java.util.List<Order> findAll() {\n"
    "        return java.util.List.copyOf(store.values());\n"
    "    }\n\n"
    "    public boolean hasOrdersForProduct(Long productId) {",
)
svc.write_text(s)
print("✓ OrderService.findAll() added")

ctl = Path("$CTL"); c = ctl.read_text()
c = c.replace(
    '    @GetMapping("/{id}")\n'
    "    public Order getOrder(@PathVariable Long id) {",
    "    @GetMapping\n"
    "    public java.util.List<Order> getAllOrders() {\n"
    "        return orderService.findAll();\n"
    "    }\n\n"
    '    @GetMapping("/{id}")\n'
    "    public Order getOrder(@PathVariable Long id) {",
)
ctl.write_text(c)
print("✓ GET /api/v1/orders endpoint added to OrderController")
PY

git add "$SVC" "$CTL"   # commit ONLY these two files, never -A
git commit -q -m "feat: list all orders via GET /api/v1/orders"
echo
echo "✅ Committed. When you're ready to demo, run:  git push"
echo "   → 'generate-tests' fires; expect a PR with NEW Java step definitions"
echo "     (a STEPDEF block) plus scenarios listing orders. This is the finale."
