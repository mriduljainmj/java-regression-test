# web-ui — Product Catalog UI + browser automation

A small, self-contained web page that exercises the **Products API contract**
(`java-component`) through a browser, plus a **Cucumber + Playwright** suite that
drives it. It gives the repo a real UI for UI-automation, in the same BDD
(`.feature` + step definitions) style as the Java (Cucumber) and .NET (SpecFlow)
components.

## What the UI does

`public/` is a static Product Catalog with client-side logic that mirrors the
backend rules, so the tests assert the same observable behaviour the API enforces:

| Behaviour | Rule (mirrors `ProductRequest` / `ProductService`) |
|---|---|
| Add product | name required (`name must not be blank`), ≤ 100 chars |
| Add product | price required, `> 0`, `≤ 300000.00` |
| Filter | `minPrice` must not be greater than `maxPrice` |
| Delete | removes the product from the catalog |

The catalog is seeded deterministically (Wireless Keyboard, USB-C Hub, 4K Monitor)
so scenarios can assert exact counts. Each scenario runs in a fresh browser
context, so state resets between scenarios.

## Run the UI

```bash
cd web-ui
npm run serve          # → http://localhost:4173
```

## Run the browser tests

```bash
cd web-ui
npm install
npm run test:install   # one-time: downloads the Chromium browser for Playwright
npm test
```

The test hooks start the static server automatically, so `npm test` is
self-contained. An HTML report is written to `reports/ui-report.html`.

To run against an already-running server (e.g. a deployed build), set `BASE_URL`:

```bash
BASE_URL=http://localhost:4173 npm test
```

## Layout

```
web-ui/
  public/                     the UI (index.html, styles.css, app.js)
  serve.js                    zero-dependency static server
  features/
    product_catalog.feature   Gherkin scenarios (happy + negative paths)
    steps/                     Playwright-driven step definitions
    support/hooks.js           browser + server lifecycle
  cucumber.js                 Cucumber config
```

## How this fits the pipeline

These UI `.feature` files follow the same Gherkin format the testgen agent already
produces for the API components, so the agent can later be extended to generate
UI scenarios from front-end diffs the same way it does for controllers.
