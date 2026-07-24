import http from "node:http";
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { Before, After, BeforeAll, AfterAll, Status, setDefaultTimeout } from "@cucumber/cucumber";
import { chromium } from "playwright";
import { log } from "./logger.js";

setDefaultTimeout(30000);

const HERE = fileURLToPath(new URL(".", import.meta.url)); // tests/support/
const PKG_ROOT = join(HERE, "..", ".."); // frontend-react/
const SHOTS_DIR = join(PKG_ROOT, "reports", "screenshots");
const PORT = process.env.PORT || 4174;
const BASE_URL = process.env.BASE_URL || `http://localhost:${PORT}`;

let browser;
let server; // static server for dist/ we start ourselves (unless BASE_URL is provided)

const slug = (s) => (s || "scenario").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();

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
          if (Date.now() - start > timeoutMs) reject(new Error(`static server did not start at ${url}`));
          else setTimeout(ping, 150);
        });
    })();
  });
}

BeforeAll(async function () {
  if (!process.env.BASE_URL) {
    // serve-dist.js lives at the package root (two levels up from tests/support/).
    server = spawn(process.execPath, [join(PKG_ROOT, "serve-dist.js")], {
      stdio: "inherit",
      env: { ...process.env, PORT: String(PORT) }
    });
    await waitForServer(`${BASE_URL}/`);
  }
  browser = await chromium.launch();
  log.info(`browser launched; serving ${BASE_URL}`);
});

AfterAll(async function () {
  if (browser) await browser.close();
  if (server) server.kill();
});

// Fresh browser context per scenario → the app remounts and re-seeds, so every
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
  if (result?.status === Status.FAILED && this.page) {
    try {
      const png = await this.page.screenshot({ fullPage: true });
      await this.attach(png, "image/png");
      await mkdir(SHOTS_DIR, { recursive: true });
      const file = join(SHOTS_DIR, `${slug(pickle.name)}-${Date.now()}.png`);
      await writeFile(file, png);
      log.error(`✖ FAILED: ${pickle.name} — screenshot saved to ${file}`);
    } catch (e) {
      log.error(`✖ FAILED: ${pickle.name} — could not capture screenshot: ${e.message}`);
    }
  } else {
    log.info(`✔ ${result?.status ?? "done"}: ${pickle.name}`);
  }
  if (this.context) await this.context.close();
});
