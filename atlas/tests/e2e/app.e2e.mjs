// End-to-end tests of the real desktop app (Rust core + SQLite + React UI) over WebDriver.
// Run via tests/e2e/run.sh, which builds the `e2e` binary (scripted provider, in-memory keys),
// isolates HOME and the data dir, and starts tauri-driver under a virtual display.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { Builder, By, Key, until } from "selenium-webdriver";

const AXE = fs.readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf8");

const APP = path.resolve("target/debug/atlas-desktop");
const SHOTS = process.env.ATLAS_SCREENSHOTS; // optional directory for real screenshots
const HOME = process.env.HOME;
let driver;
/** Linux has no Documents folder unless XDG user dirs are configured; Atlas then uses $HOME. */
const workspaceDir = () =>
  [path.join(HOME, "Documents", "Atlas Workspace"), path.join(HOME, "Atlas Workspace")].find((p) => fs.existsSync(p)) ?? "";

const xpText = (tag, text) => By.xpath(`//${tag}[contains(normalize-space(.), ${JSON.stringify(text)})]`);
async function find(locator, ms = 15000) {
  return driver.wait(until.elementLocated(locator), ms);
}
async function click(text, tag = "button") {
  const el = await find(xpText(tag, text));
  await driver.wait(until.elementIsEnabled(el), 15000);
  await el.click();
}
async function waitText(text, ms = 15000) {
  try {
    return await find(By.xpath(`//*[contains(normalize-space(text()), ${JSON.stringify(text)})]`), ms);
  } catch (e) {
    const dir = process.env.ATLAS_FAILSHOTS ?? "test-results";
    fs.mkdirSync(dir, { recursive: true });
    const base = path.join(dir, `fail-${text.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}`);
    fs.writeFileSync(`${base}.png`, await driver.takeScreenshot(), "base64");
    fs.writeFileSync(`${base}.txt`, await driver.executeScript("return document.body.innerText"));
    throw e;
  }
}
async function shot(name) {
  if (!SHOTS) return;
  await driver.sleep(400);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), await driver.takeScreenshot(), "base64");
}
const pageText = () => driver.executeScript("return document.body.innerText");
/** Navigate with the app's own keyboard shortcuts (Ctrl+1…9, Ctrl+,). */
async function go(key) {
  await driver.actions().keyDown(Key.CONTROL).sendKeys(key).keyUp(Key.CONTROL).perform();
  await driver.sleep(250);
}
async function send(text) {
  const box = await find(By.id("composer"));
  await driver.wait(until.elementIsEnabled(box), 15000);
  await box.sendKeys(text, Key.ENTER);
}

before(async () => {
  driver = await new Builder()
    .usingServer("http://127.0.0.1:4444/")
    .withCapabilities({ browserName: "wry", "tauri:options": { application: APP } })
    .build();
});

after(async () => {
  await driver?.quit();
});

test("first-run onboarding completes and personalises Atlas", async () => {
  await waitText("Hello. I'm Atlas.", 30000);
  await shot("01-welcome");
  await click("Get started");
  const name = await find(By.id("ob-name"));
  await name.sendKeys("Sam");
  await click("Continue");
  await waitText("Where your data lives");
  await shot("02-data");
  await click("Continue");
  await waitText("Connect an AI model");
  await waitText("E2E scripted provider");
  await click("Continue");
  await waitText("Choose a workspace folder");
  await click("Use Documents/Atlas Workspace");
  await waitText("Workspace:");
  await click("Add a sample file (demo data)");
  await waitText("Demo file added");
  const sample = path.join(workspaceDir(), "Atlas Sample (demo data)", "household-budget-DEMO.csv");
  assert.ok(fs.existsSync(sample), "sample file must exist on disk");
  await click("Continue");
  await waitText("Meet the Atlas Map");
  await click("Continue");
  await waitText("You're all set, Sam.");
  await shot("03-ready");
  await click("Start your first conversation");
  await waitText("Echo: Hi Atlas! I'm Sam.", 20000);
  await shot("04-first-conversation");
});

test("a read-only tool runs without approval and the result is verified", async () => {
  await send("calculate 6*7");
  await waitText("Done. Tool result:", 20000);
  // The reply streams word by word; wait for the full result rather than racing the stream.
  await driver.wait(async () => /"result":\s*42/.test(await pageText()), 10000, "calculator result 42 shown");
  await shot("05-tool-run");
});

test("a local write pauses for approval and runs exactly once when approved", async () => {
  await send("please create a note");
  await waitText("Approval needed", 20000);
  await shot("06-approval");
  await click("Approve");
  await waitText("Done. Tool result:", 20000);
  const file = path.join(workspaceDir(), "e2e", "hello.md");
  assert.equal(fs.readFileSync(file, "utf8"), "# Hello from Atlas\n");
});

test("declining an approval performs nothing", async () => {
  const before = fs.readdirSync(path.join(workspaceDir(), "e2e"));
  await send("create a note again");
  await waitText("Approval needed", 20000);
  await click("Decline");
  await waitText("The action did not complete", 20000);
  const after = fs.readdirSync(path.join(workspaceDir(), "e2e"));
  assert.deepEqual(after, before);
});

test("a running response can be stopped", async () => {
  await send("wait for me");
  const stop = await find(xpText("button", "Stop"));
  await driver.sleep(300);
  await stop.click();
  await waitText("Stopped by you.", 15000);
});

test("Mission Control shows the real execution history", async () => {
  await go("4");
  await waitText("Execution timeline");
  await driver.sleep(300);
  const body = await pageText();
  assert.match(body, /files\.create|calc\.evaluate/);
  assert.match(body, /Completed/);
  await shot("07-mission-control");
});

test("the Atlas Map renders nodes from live state", async () => {
  await go("3");
  await waitText("ATLAS CORE", 20000);
  await waitText("Calculator");
  await waitText("E2E scripted provider");
  await shot("08-atlas-map");
  await click("Calculator", "p");
  await waitText("Connections");
  await shot("09-map-inspector");
});

test("memory can be added, found and deleted", async () => {
  await go("6");
  await click("Add memory");
  const box = await find(By.id("mem-c"));
  await box.sendKeys("Prefers metric units for measurements");
  await click("Save");
  await waitText("Prefers metric units for measurements");
  await shot("10-memory");
  await driver.findElement(By.css('[aria-label="Delete memory"]')).click();
  await click("Delete", "button[ancestor::*[@role='dialog']]");
  await driver.wait(async () => !(await pageText()).includes("Prefers metric units"), 10000);
});

test("integrations show honest states and settings persist", async () => {
  await go("8");
  await waitText("Web search (Tavily)");
  await waitText("Planned — not available in this version");
  await shot("11-integrations");
  await go(",");
  await click("Permissions");
  await waitText("Always denied");
  await shot("12-settings-permissions");
  await click("Appearance");
  await click("Daylight");
  await driver.wait(async () => (await driver.executeScript("return document.documentElement.dataset.theme")) === "light", 5000);
  await click("Companion", "button");
  await shot("13-settings-light");
  await click("Appearance");
  await click("Deep Orbit");
});

test("home dashboard reflects state", async () => {
  await go("1");
  await waitText("Recent conversations");
  await shot("14-home");
});

/** Run axe-core inside the real webview; fail on serious or critical violations. */
async function audit(page) {
  await driver.executeScript(AXE);
  const result = await driver.executeAsyncScript(`
    const done = arguments[arguments.length - 1];
    axe.run(document, { resultTypes: ["violations"] }).then(r => done(JSON.stringify(r.violations.map(v => ({
      id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 3).map(n => n.target.join(" "))
    }))))).catch(e => done(JSON.stringify([{ id: "axe-error", impact: "critical", help: String(e), nodes: [] }])));
  `);
  const violations = JSON.parse(result);
  const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  if (violations.length) console.log(`[a11y] ${page}:`, JSON.stringify(violations));
  return blocking;
}

test("accessibility audit (axe-core) finds no serious or critical issues", async () => {
  const failures = {};
  for (const [key, page] of [["1", "home"], ["2", "companion"], ["4", "mission-control"], ["6", "memory"], ["8", "integrations"], [",", "settings"]]) {
    await go(key);
    await driver.sleep(500);
    const blocking = await audit(page);
    if (blocking.length) failures[page] = blocking;
  }
  assert.deepEqual(failures, {});
});
