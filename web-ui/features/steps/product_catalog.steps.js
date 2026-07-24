const assert = require("node:assert");
const { Given, When, Then } = require("@cucumber/cucumber");
const { log } = require("../support/logger");

// Each step logs its action via the shared logger; the After hook screenshots
// on failure (see features/support/hooks.js).

function rowSelector(name) {
  return `[data-testid=product-row][data-name="${name}"]`;
}

async function waitForRowCount(page, expected) {
  await page.waitForFunction(
    (n) => document.querySelectorAll("[data-testid=product-row]").length === n,
    expected,
    { timeout: 5000 }
  );
}

Given("I am on the product catalog page", async function () {
  log.step("open the product catalog page");
  await this.page.locator("[data-testid=add-btn]").waitFor({ state: "visible" });
});

When("I add a product named {string} priced {string}", async function (name, price) {
  log.step(`add a product named "${name}" priced "${price}"`);
  await this.page.fill("[data-testid=name-input]", name);
  await this.page.fill("[data-testid=price-input]", price);
  await this.page.click("[data-testid=add-btn]");
});

When("I filter products with min price {string} and max price {string}", async function (min, max) {
  log.step(`filter products by price ${min}–${max}`);
  await this.page.fill("[data-testid=min-price]", min);
  await this.page.fill("[data-testid=max-price]", max);
  await this.page.click("[data-testid=apply-filter]");
});

When("I delete the product {string}", async function (name) {
  log.step(`delete the product "${name}"`);
  await this.page.click(`${rowSelector(name)} [data-testid=delete-btn]`);
});

Then("the product {string} appears in the catalog", async function (name) {
  log.step(`assert product "${name}" appears`);
  await this.page.locator(rowSelector(name)).waitFor({ state: "visible" });
});

Then("the product {string} is no longer in the catalog", async function (name) {
  log.step(`assert product "${name}" is gone`);
  const count = await this.page.locator(rowSelector(name)).count();
  assert.strictEqual(count, 0, `expected "${name}" to be gone, found ${count} row(s)`);
});

// Handles both "1 product" and "N products".
Then(/^the catalog shows (\d+) products?$/, async function (n) {
  log.step(`assert the catalog shows ${n} product(s)`);
  await waitForRowCount(this.page, Number(n));
});

Then("I see the validation error {string}", async function (message) {
  log.step(`assert validation error "${message}"`);
  const alert = this.page.locator("[data-testid=alert]");
  await alert.waitFor({ state: "visible" });
  const text = (await alert.textContent()) || "";
  assert.ok(text.includes(message), `alert text "${text}" should contain "${message}"`);
});

Then("I see the confirmation {string}", async function (message) {
  log.step(`assert confirmation "${message}"`);
  const alert = this.page.locator("[data-testid=alert]");
  await alert.waitFor({ state: "visible" });
  const text = (await alert.textContent()) || "";
  assert.ok(text.includes(message), `alert text "${text}" should contain "${message}"`);
});
