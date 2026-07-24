# frontend-react — React Product Catalog + UI automation

A **second frontend** — same app as `web-ui/`, but written in **React (Vite)** instead
of plain HTML/JS. It exists to prove the point behind the agent's UI mode: **UI
automation targets the rendered DOM, not the source framework.** The Cucumber
`.feature` and Playwright step definitions here are byte-for-byte the same shape as
the plain-HTML ones — because both render to the same DOM (`data-testid` hooks).

The catalog mirrors the Products API contract (`java-component` `ProductRequest` /
`ProductService`): name required / ≤ 100 chars, price `> 0` and `≤ 300000.00`, and a
price-range filter. It is seeded deterministically so scenarios assert exact counts.

## Run the app

```bash
cd frontend-react
npm install
npm run dev            # Vite dev server (hot reload) → http://localhost:5173
# or the production build:
npm run build && npm run preview   # serves dist/ → http://localhost:4174
```

## Run the browser tests

```bash
cd frontend-react
npm install
npm run test:install   # one-time: downloads Chromium for Playwright
npm test               # builds the app, starts a static server, runs Cucumber + Playwright
```

`npm test` = `vite build && cucumber-js`. The hooks start a static server over `dist/`,
so the run is self-contained. Reports land in `reports/`.

## How the agent generates these

The testgen agent's **UI mode** (`project_type: "ui"`) detects a frontend change
under `frontend-react/src/**` and generates a Playwright + Cucumber `.feature` +
`*.steps.js` the same way it generates RestAssured/SpecFlow tests for controllers.
It then runs `npm test` here and self-corrects on failure — the same
generate → validate → run → fix loop as the backend components.

## Layout

```
frontend-react/
  src/ProductCatalog.jsx    the React UI under test
  src/main.jsx, styles.css
  serve-dist.js             static server for the built dist/
  vite.config.js
  tests/
    features/*.feature      Gherkin scenarios
    steps/*.steps.js        Playwright-driven step definitions (DOM-level)
    support/hooks.js        browser + server lifecycle; screenshots on failure
    support/logger.js       shared timestamped logger used by the steps
  cucumber.mjs              Cucumber config (ESM — see the note inside it)
```

## Logs & failure screenshots

Each step logs what it did (`STEP add a product named "…"`), and every scenario
logs `▶ Scenario:` / `✔ PASSED:`. When a scenario **fails**, the `After` hook saves a
full-page screenshot to `reports/screenshots/<scenario>-<timestamp>.png` **and**
embeds it in `reports/ui-report.html` inline next to the failing step.
