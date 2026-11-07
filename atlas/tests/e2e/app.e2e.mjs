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

const APP = path.resolve(process.platform === "win32" ? "target/debug/atlas-desktop.exe" : "target/debug/atlas-desktop");
const SHOTS = process.env.ATLAS_SCREENSHOTS; // optional directory for real screenshots
let driver;
let WORKSPACE = "";
/** The workspace folder as the app itself reports it (Documents differs per OS and setup). */
async function loadWorkspace() {
  const settings = await driver.executeAsyncScript(
    "const done = arguments[arguments.length - 1]; window.__TAURI_INTERNALS__.invoke('settings_get').then(done, (e) => done(null));",
  );
  WORKSPACE = settings?.workspace_dir ?? "";
  assert.ok(WORKSPACE, "the app reports a workspace folder");
}
const workspaceDir = () => WORKSPACE;

const xpText = (tag, text) => By.xpath(`//${tag}[contains(normalize-space(.), ${JSON.stringify(text)})]`);
async function find(locator, ms = 15000) {
  return driver.wait(until.elementLocated(locator), ms);
}
async function click(text, tag = "button") {
  const el = await find(xpText(tag, text));
  await driver.wait(until.elementIsEnabled(el), 15000);
  await el.click();
}
/** Wait until `text` is visible on the page (matches across text nodes, unlike an XPath text() test). */
async function waitText(text, ms = 15000) {
  try {
    await driver.wait(async () => (await driver.executeScript("return document.body.innerText")).includes(text), ms, `text "${text}"`);
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
/** Occurrences of `text` on the page, to wait for a new reply rather than matching an earlier one. */
async function countText(text) {
  return (await pageText()).split(text).length - 1;
}
async function waitForMore(text, before, ms = 20000) {
  await driver.wait(async () => (await countText(text)) > before, ms, `a new "${text}"`);
}
/** Atlas ignores Enter while it is responding (the composer shows Stop), so wait until it is idle. */
async function waitIdle(ms = 20000) {
  await driver.wait(async () => (await driver.findElements(xpText("button", "Stop"))).length === 0, ms, "Atlas idle");
}
async function send(text) {
  await waitIdle();
  // The composer can re-render between lookup and typing; retry on a stale reference.
  for (let attempt = 0; ; attempt++) {
    try {
      const box = await find(By.id("composer"));
      await driver.wait(until.elementIsEnabled(box), 15000);
      await box.sendKeys(text, Key.ENTER);
      return;
    } catch (e) {
      if (e?.name !== "StaleElementReferenceError" || attempt >= 4) throw e;
      await driver.sleep(200);
    }
  }
}

before(async () => {
  driver = await new Builder()
    .usingServer("http://127.0.0.1:4444/")
    // On Windows, `webviewOptions` puts msedgedriver into WebView2 mode; without it msedgedriver treats the
    // app as an Edge browser binary and waits for a DevToolsActivePort file that never appears.
    .withCapabilities({
      browserName: "wry",
      "tauri:options": process.platform === "win32" ? { application: APP, webviewOptions: {} } : { application: APP },
    })
    .build();
});

after(async () => {
  await driver?.quit();
});

test("first-run onboarding completes and personalises Atlas", async () => {
  await waitText("Hello. I'm Atlas.", 30000);
  // The startup splash fades out over the first screen; wait until it has been removed.
  await driver.wait(async () => (await driver.findElements(By.css("[data-splash]"))).length === 0, 15000, "splash removed");
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
  await loadWorkspace();
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
  const before = await countText("Done. Tool result:");
  await send("calculate 6*7");
  await waitForMore("Done. Tool result:", before);
  // The reply streams word by word; wait for the full result rather than racing the stream.
  await driver.wait(async () => /"result":\s*42/.test(await pageText()), 10000, "calculator result 42 shown");
  await shot("05-tool-run");
});

test("a local write pauses for approval and runs exactly once when approved", async () => {
  const before = await countText("Done. Tool result:");
  await send("please create a note");
  await waitText("Approval needed", 20000);
  await shot("06-approval");
  await click("Approve");
  await waitForMore("Done. Tool result:", before);
  await waitIdle();
  const file = path.join(workspaceDir(), "e2e", "hello.md");
  assert.equal(fs.readFileSync(file, "utf8"), "# Hello from Atlas\n");
});

test("declining an approval performs nothing", async () => {
  const before = fs.readdirSync(path.join(workspaceDir(), "e2e"));
  await send("create a note again");
  await waitText("Approval needed", 20000);
  await click("Decline");
  await waitText("The action did not complete", 20000);
  await waitIdle();
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
  await go("5");
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
  await go("7");
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
  await go("9");
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

test("Atlas Forge: explorer, approved edit with revertible snapshot, terminal", async () => {
  await go("4");
  await waitText("e2e-sample");
  await click("main.py", "button");
  await waitText("return a - b");
  await click("Session", "button");
  await send("Please fix the bug in add");
  await waitText("Waiting for your approval", 20000);
  await waitText("+    return a + b");
  // The floating approval dock can overlap the card in the session pane; use the in-pane button.
  const approve = await find(By.xpath("//section[@aria-label='Forge workspace']//button[normalize-space()='Approve']"));
  await driver.executeScript("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", approve);
  await waitText("Done. Tool result", 20000);
  await click("Changes", "button");
  await waitText("edited");
  await shot("15-forge");
  await click("Terminal", "button");
  const cmd = await find(By.css('input[aria-label="Command"]'));
  await cmd.sendKeys("git --version", Key.ENTER);
  await waitText("git version", 20000);
  await shot("16-forge-terminal");
});

test("Siblings: honest unpaired state, nothing shown as connected", async () => {
  await (await find(By.css('nav[aria-label="Main"] button[aria-label="Siblings"]'))).click();
  await waitText("No sibling paired");
  const state = await driver.executeScript("return document.querySelector('[data-avatar-state]')?.dataset.avatarState");
  assert.equal(state, "offline");
  await click("Pair with Prometheus");
  await waitText("python sibling_adapter.py --pair");
  await shot("17-siblings-pair");
  await driver.actions().sendKeys(Key.ESCAPE).perform();
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
  for (const [key, page] of [["1", "home"], ["2", "companion"], ["4", "forge"], ["siblings", "siblings"], ["5", "mission-control"], ["7", "memory"], ["9", "integrations"], [",", "settings"]]) {
    if (key === "siblings") await (await find(By.css('nav[aria-label="Main"] button[aria-label="Siblings"]'))).click();
    else await go(key);
    await driver.sleep(500);
    const blocking = await audit(page);
    if (blocking.length) failures[page] = blocking;
  }
  assert.deepEqual(failures, {});
});
