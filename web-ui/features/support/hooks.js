const path = require("path");
const http = require("http");
const fs = require("fs/promises");
const { spawn } = require("child_process");
const {
  Before,
  After,
  BeforeAll,
  AfterAll,
  Status,
  setDefaultTimeout
} = require("@cucumber/cucumber");
const { chromium } = require("playwright");
const { log } = require("./logger");

setDefaultTimeout(30000);

const PORT = process.env.PORT || 4173;
const BASE_URL = process.env.BASE_URL || `http://localhost:${PORT}`;
const SHOTS_DIR = path.join(__dirname, "..", "..", "reports", "screenshots");
// HEADLESS=false (or 0) opens a real visible browser window so you can watch
// the run. SLOWMO (ms) optionally slows each Playwright action for readability.
const HEADLESS = !["false", "0"].includes((process.env.HEADLESS || "").toLowerCase());
const SLOW_MO = Number(process.env.SLOWMO || 0);

const slug = (s) => (s || "scenario").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();

let browser;
let server; // static server we start ourselves (unless BASE_URL is provided)

function waitForServer(url, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function ping() {
      http
        .get(url, (res) => {
          res.resume();
          resolve();
        })
        .on("error", () => {
          if (Date.now() - start > timeoutMs) {
            reject(new Error(`static server did not start at ${url}`));
          } else {
            setTimeout(ping, 150);
          }
        });
    })();
  });
}

BeforeAll(async function () {
  // Start our own static server unless the caller points us at a running one.
  if (!process.env.BASE_URL) {
    server = spawn(process.execPath, [path.join(__dirname, "..", "..", "serve.js")], {
      stdio: "inherit",
      env: Object.assign({}, process.env, { PORT: String(PORT) })
    });
    await waitForServer(`${BASE_URL}/`);
  }
  browser = await chromium.launch({ headless: HEADLESS, slowMo: SLOW_MO });
  log.info(`browser launched (headless=${HEADLESS}${SLOW_MO ? `, slowMo=${SLOW_MO}ms` : ""}); serving ${BASE_URL}`);
});

AfterAll(async function () {
  if (browser) await browser.close();
  if (server) server.kill();
});

// Fresh browser context per scenario → the page reloads and re-seeds, so every
// scenario starts from the same deterministic catalog.
Before(async function ({ pickle }) {
  this.context = await browser.newContext();
  this.page = await this.context.newPage();
  await this.page.goto(`${BASE_URL}/`);
  log.info(`▶ Scenario: ${pickle.name}`);
});

// On failure, grab a full-page screenshot: saved to reports/screenshots/ AND
// attached to the Cucumber HTML report so it renders inline next to the failure.
After(async function ({ pickle, result }) {
  if (result && result.status === Status.FAILED && this.page) {
    try {
      const png = await this.page.screenshot({ fullPage: true });
      await this.attach(png, "image/png");
      await fs.mkdir(SHOTS_DIR, { recursive: true });
      const file = path.join(SHOTS_DIR, `${slug(pickle.name)}-${Date.now()}.png`);
      await fs.writeFile(file, png);
      log.error(`✖ FAILED: ${pickle.name} — screenshot saved to ${file}`);
    } catch (e) {
      log.error(`✖ FAILED: ${pickle.name} — could not capture screenshot: ${e.message}`);
    }
  } else {
    log.info(`✔ ${(result && result.status) || "done"}: ${pickle.name}`);
  }
  if (this.context) await this.context.close();
});
